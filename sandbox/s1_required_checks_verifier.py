#!/usr/bin/env python3
"""S1 verifier: run a head's own declared required checks offline, twice, and bind each result to the head.

StegVerse-org/.github#162 (INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001), S1
home #163. Generalizes sandbox/s1_hop_head_verifier.py (which runs only the
`intr-destination-hop/hop` check, and is kept byte-unchanged so its receipts
re-derive) to whatever checks the head declares.

Where the checks are declared. P1's SV-CHANGE-REQUIRED-CHECKS-001 row is the
source once published; until then the head's own interim declaration
`.sv/required-checks.json` is read, and the receipt says so
(`declaration_basis`). Each declared check is an id, an offline command and its
expected outcome:

  {"id": ..., "kind": "python-unittest", "target": "tests/test_x.py", "expected_outcome": "PASS"}
  {"id": ..., "kind": "argv", "argv": ["python", "-B", "x.py"], "expected_outcome": "PASS"}

`python-unittest` runs through sandbox/s1_probe/s1_unittest_runner.py, which
prints only test ids and outcomes; `argv` binds raw stdout/stderr. PASS means
exit code 0. A declaration may name `dependencies` (a repository at an exact
commit, exposed to the checks through a named environment variable); each is
materialized from a supplied `--dependency id=<git checkout>`, never fetched.

Each check runs with no inherited credentials or ledger locations, a fixed git
identity and date, HOME in the sandbox, and sandbox/s1_probe/sitecustomize.py
recording every wall-clock and network read (network is refused). The whole
set runs twice, in the same path, from fresh materializations.

Dispositions (every non-ALLOW carries the six fields):
  FAIL_CLOSED  S1_INPUT_*, HEAD_NOT_MATERIALIZED, REQUIRED_CHECKS_NOT_DECLARED,
               REQUIRED_CHECKS_DECLARATION_INVALID, REQUIRED_CHECK_DEPENDENCY_NOT_SUPPLIED,
               REQUIRED_CHECK_DID_NOT_COMPLETE
  DENY         REQUIRED_CHECK_READS_THE_CLOCK, REQUIRED_CHECK_READS_THE_NETWORK,
               REQUIRED_CHECK_OUTPUT_DIFFERS_ACROSS_TWO_RUNS, REQUIRED_CHECK_FAILED_AT_HEAD
  ALLOW        every declared check passed, read no clock or network, and printed the same bytes twice

The verifier reads no clock, opens no network connection and passes no
credential; the receipt is canonical JSON and admission-input evidence only.
Exit code 0 only for ALLOW.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROBE = HERE / "s1_probe"
RUNNER = PROBE / "s1_unittest_runner.py"
RECEIPT_SCHEMA = "stegverse.sv-llm.s1-required-checks-verification-receipt/v1"
INPUT_SCHEMA = "stegverse.sv-change.s1-required-checks-input/v1"
INPUT_TYPE = "SV_CHANGE"
INPUT_TYPE_DEFINITION = "PENDING_P1_S0_SV_CHANGE (StegVerse-org/.github#163)"
DECLARATION_PATH = ".sv/required-checks.json"
DECLARATION_SCHEMA = "stegverse.sv-change.required-checks-declaration/v0-interim"
P1_ROW = "SV-CHANGE-REQUIRED-CHECKS-001"
DECLARATION_BASIS = ("INTERIM_PER_REPOSITORY_DECLARATION (" + DECLARATION_PATH + " at the head) until P1's "
                     + P1_ROW + " row is published")
KINDS = ("python-unittest", "argv")
CHECK_TIMEOUT_S = 900
FIXED_GIT_DATE = "@0 +0000"
OWNING_EXISTING_GOAL = "StegVerse-org/.github#162 / INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
RETRY_ENTRYPOINT = ("sandbox/s1_required_checks_verifier.py --input <sv-change.json> --checkout <git checkout> "
                    "[--dependency <id>=<git checkout>]")
EVIDENCE_ROLE = "ADMISSION_INPUT_EVIDENCE_ONLY"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
CHECK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
RESERVED_ENV = ("PATH", "HOME", "PYTHONPATH", "S1_PROBE_LOG")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Refused(Exception):
    def __init__(self, disposition: str, code: str, predicate: str, repair: str, next_attempt: str,
                 detail: str) -> None:
        super().__init__(code)
        self.disposition = disposition
        self.detail = detail
        self.fields = {"failure_code": code, "failed_predicate": predicate, "required_evidence_or_repair": repair,
                       "retry_entrypoint": RETRY_ENTRYPOINT, "owning_existing_goal": OWNING_EXISTING_GOAL,
                       "next_attempt": next_attempt}


def base_env(home: Path | None) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
           "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_NAME": "sv-llm-s1-sandbox", "GIT_AUTHOR_EMAIL": "s1-sandbox@example.invalid",
           "GIT_COMMITTER_NAME": "sv-llm-s1-sandbox", "GIT_COMMITTER_EMAIL": "s1-sandbox@example.invalid",
           "GIT_AUTHOR_DATE": FIXED_GIT_DATE, "GIT_COMMITTER_DATE": FIXED_GIT_DATE}
    if home is not None:
        env["HOME"] = str(home)
    return env


def git(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, env=base_env(None))


def head_present(checkout: Path | None, commit: str) -> bool:
    if checkout is None or not checkout.exists():
        return False
    resolved = git(checkout, "rev-parse", "--verify", "--quiet", commit + "^{commit}")
    return resolved.returncode == 0 and resolved.stdout.decode().strip() == commit


def materialize(checkout: Path, commit: str, dest: Path) -> str:
    """Extract exactly ``commit``'s tree into ``dest``; return the tree id."""
    tree = git(checkout, "rev-parse", commit + "^{tree}").stdout.decode().strip()
    archive = git(checkout, "archive", "--format=tar", commit)
    if archive.returncode != 0:
        raise OSError("git archive failed")
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk() or member.name.startswith("/") or ".." in Path(member.name).parts:
                continue
            tar.extract(member, dest, filter="data") if hasattr(tarfile, "data_filter") else tar.extract(member, dest)
    return tree


def read_input(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), raw
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refused("FAIL_CLOSED", "S1_INPUT_NOT_READABLE", "S1_INPUT_IS_A_READABLE_JSON_SV_CHANGE",
                      "a UTF-8 JSON file declaring the SV_CHANGE to verify", "re-run with a readable input file",
                      type(exc).__name__) from None


def validate_input(document: Any) -> dict[str, Any]:
    def bad(detail: str) -> Refused:
        return Refused("FAIL_CLOSED", "S1_INPUT_NOT_A_DECLARED_SV_CHANGE", "S1_INPUT_DECLARES_ONE_SV_CHANGE_HEAD",
                       "an input with schema " + INPUT_SCHEMA + ", type " + INPUT_TYPE
                       + ", repository <owner>/<repo>, pull_request <int>, head_sha <40 lowercase hex>",
                       "re-run with the corrected input; nothing was run", detail)
    if not isinstance(document, dict):
        raise bad("input is not an object")
    if document.get("schema") != INPUT_SCHEMA:
        raise bad("schema " + repr(document.get("schema")))
    if document.get("type") != INPUT_TYPE:
        raise bad("type " + repr(document.get("type")))
    repository, number, head = document.get("repository"), document.get("pull_request"), document.get("head_sha")
    if not isinstance(repository, str) or not REPOSITORY.match(repository):
        raise bad("repository " + repr(repository))
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise bad("pull_request " + repr(number))
    if not isinstance(head, str) or not HEX40.match(head):
        raise bad("head_sha " + repr(head))
    return {"repository": repository, "pull_request": number, "head_sha": head}


def invalid_declaration(detail: str) -> Refused:
    return Refused("FAIL_CLOSED", "REQUIRED_CHECKS_DECLARATION_INVALID", "THE_HEAD_DECLARES_ITS_REQUIRED_CHECKS",
                   DECLARATION_PATH + " with schema " + DECLARATION_SCHEMA + " and checks [{id, kind (" + ", ".join(KINDS)
                   + "), target|argv, expected_outcome PASS}], optional dependencies [{id, repository, commit, env}] "
                   "and env {NAME: value}",
                   "correct the declaration at a new head and re-run", detail)


def read_declaration(head_root: Path) -> tuple[dict[str, Any], bytes]:
    path = head_root / DECLARATION_PATH
    if not path.is_file():
        raise Refused("FAIL_CLOSED", "REQUIRED_CHECKS_NOT_DECLARED", "THE_HEAD_DECLARES_ITS_REQUIRED_CHECKS",
                      "P1's " + P1_ROW + " row for this repository, or (interim) " + DECLARATION_PATH
                      + " at the head listing each required check as an id, an offline command and its expected outcome",
                      "declare the required checks at a new head and re-run; nothing was run",
                      "no " + DECLARATION_PATH + " at the head and no published " + P1_ROW + " row")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise invalid_declaration(type(exc).__name__) from None
    if not isinstance(document, dict) or document.get("schema") != DECLARATION_SCHEMA:
        raise invalid_declaration("schema " + repr(document.get("schema") if isinstance(document, dict) else None))
    checks = document.get("checks")
    if not isinstance(checks, list) or not checks:
        raise invalid_declaration("checks must be a non-empty list")
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str) or not CHECK_ID.match(check["id"]):
            raise invalid_declaration("check id " + repr(check.get("id") if isinstance(check, dict) else check))
        if check["id"] in seen:
            raise invalid_declaration("duplicate check id " + check["id"])
        seen.add(check["id"])
        if check.get("kind") not in KINDS or check.get("expected_outcome") != "PASS":
            raise invalid_declaration(check["id"] + ": kind/expected_outcome")
        if check["kind"] == "python-unittest":
            target = check.get("target")
            if not isinstance(target, str) or target.startswith("/") or ".." in Path(target).parts \
                    or not (head_root / target).is_file():
                raise invalid_declaration(check["id"] + ": target " + repr(target))
        else:
            argv = check.get("argv")
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise invalid_declaration(check["id"] + ": argv")
    dependencies = document.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise invalid_declaration("dependencies must be a list")
    for dependency in dependencies:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("id"), str) \
                or not CHECK_ID.match(dependency["id"]) or not isinstance(dependency.get("repository"), str) \
                or not REPOSITORY.match(dependency["repository"]) or not isinstance(dependency.get("commit"), str) \
                or not HEX40.match(dependency["commit"]) or not isinstance(dependency.get("env"), str) \
                or not ENV_NAME.match(dependency["env"]) or dependency["env"] in RESERVED_ENV:
            raise invalid_declaration("dependency " + repr(dependency))
    env = document.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and ENV_NAME.match(k) and k not in RESERVED_ENV
                                            and isinstance(v, str) for k, v in env.items()):
        raise invalid_declaration("env")
    return document, raw


def run_set(head_checkout: Path, head: str, declaration: dict[str, Any], dependencies: dict[str, Path],
            base: Path) -> list[dict[str, Any]]:
    """One run of every declared check from a fresh materialization at ``base``; same path each run."""
    if base.exists():
        shutil.rmtree(base)
    root = base / "head"
    materialize(head_checkout, head, root)
    env = base_env(base / "home")
    (base / "home").mkdir()
    for dependency in declaration.get("dependencies", []):
        target = base / "deps" / dependency["id"]
        materialize(dependencies[dependency["id"]], dependency["commit"], target)
        env[dependency["env"]] = str(target)
    env.update(declaration.get("env", {}))
    env["PYTHONPATH"] = str(PROBE)
    results = []
    for check in declaration["checks"]:
        log = base / ("probe-" + check["id"] + ".log")
        log.write_text("")
        if check["kind"] == "python-unittest":
            argv = [sys.executable, "-B", str(RUNNER), check["target"]]
        else:
            argv = [sys.executable if a == "python" else a for a in check["argv"]]
        try:
            completed = subprocess.run(argv, cwd=root, env={**env, "S1_PROBE_LOG": str(log)},
                                       capture_output=True, timeout=CHECK_TIMEOUT_S)
            code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired:
            code, stdout, stderr = None, b"", b""
        reads = sorted(set(log.read_text().split("\n")) - {""})
        if check["kind"] == "python-unittest":
            stderr = b""  # the runner prints its result on stdout only; anything else is the tests' own noise
        output = {"exit_code": code, "stdout_sha256": "sha256:" + sha256_hex(stdout),
                  "stderr_sha256": "sha256:" + sha256_hex(stderr)}
        summary: dict[str, Any] = {"id": check["id"], "kind": check["kind"],
                                   "command": check.get("target") if check["kind"] == "python-unittest" else check["argv"],
                                   "expected_outcome": check["expected_outcome"], **output,
                                   "outcome": "DID_NOT_COMPLETE" if code is None else ("PASS" if code == 0 else "FAIL"),
                                   "clock_reads": [r.split(" ", 1)[1] for r in reads if r.startswith("CLOCK ")],
                                   "network_reads": [r.split(" ", 1)[1] for r in reads if r.startswith("NETWORK ")]}
        if check["kind"] == "python-unittest" and code is not None:
            try:
                parsed = json.loads(stdout.decode("utf-8"))
                summary["tests"] = parsed["tests"]
                summary["failing_tests"] = sorted(t for t, o in parsed["outcomes"].items()
                                                  if o not in ("PASS", "SKIP", "EXPECTED_FAILURE"))
            except (UnicodeError, ValueError, KeyError, TypeError):
                summary["tests"] = None
        results.append(summary)
    return results


NONDETERMINISTIC = "NONDETERMINISTIC_ACROSS_TWO_SANDBOX_RUNS"
NOT_BOUND = "NOT_BOUND_THE_CHECK_READ_THE_CLOCK_OR_NETWORK"
OUTPUT_FIELDS = ("stdout_sha256", "stderr_sha256")


def bind(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The receipt's view of each check: a value that varied is masked, and the output of a
    check that read the clock or network is not bound, so the receipt itself re-derives byte for byte."""
    bound = []
    for a, b in zip(first, second):
        entry = {key: (a[key] if a.get(key) == b.get(key) else NONDETERMINISTIC) for key in a}
        if a["clock_reads"] or a["network_reads"] or b["clock_reads"] or b["network_reads"]:
            entry.update({key: NOT_BOUND for key in OUTPUT_FIELDS})
            entry["clock_reads"] = sorted(set(a["clock_reads"]) | set(b["clock_reads"]))
            entry["network_reads"] = sorted(set(a["network_reads"]) | set(b["network_reads"]))
        bound.append(entry)
    return bound


def verifier_files() -> dict[str, str]:
    return {name: "sha256:" + sha256_hex((HERE / name).read_bytes())
            for name in ("s1_required_checks_verifier.py", "s1_probe/sitecustomize.py",
                         "s1_probe/s1_unittest_runner.py")}


def verify(input_path: Path, checkout: Path | None, dependencies: dict[str, Path]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "stage": "S1", "environment": "SV_LLM_SANDBOX_LOCAL_OFFLINE",
        "input_type": INPUT_TYPE, "input_type_definition": INPUT_TYPE_DEFINITION, "input_schema": INPUT_SCHEMA,
        "declaration_basis": DECLARATION_BASIS, "declaration_path": DECLARATION_PATH,
        "evidence_role": EVIDENCE_ROLE, "authentic_ledger_receipt": False, "authority_effect": "NONE",
        "verifier_clock_read": False, "verifier_network_read": False, "dispatched": False,
        "credentials_passed": False, "verifier": {"paths_sha256": verifier_files()},
        "input_sha256": None, "repository": None, "pull_request": None, "head_sha": None, "head_tree": None,
        "declaration_sha256": None, "dependencies": [], "checks": [],
    }
    work = Path(tempfile.mkdtemp(prefix="sv-llm-s1rc-"))
    try:
        document, raw = read_input(input_path)
        body["input_sha256"] = sha256_hex(raw)
        inputs = validate_input(document)
        body.update(inputs)
        head = inputs["head_sha"]
        if not head_present(checkout, head):
            raise Refused("FAIL_CLOSED", "HEAD_NOT_MATERIALIZED", "THE_DECLARED_HEAD_IS_PRESENT_IN_THE_CHECKOUT",
                          "--checkout naming a local git checkout that holds commit " + head
                          + " (fetch it; the verifier itself never fetches)",
                          "re-run once the checkout holds the declared head", "commit not present")
        probe_root = work / "declared"
        body["head_tree"] = materialize(checkout, head, probe_root)
        declaration, declaration_raw = read_declaration(probe_root)
        body["declaration_sha256"] = "sha256:" + sha256_hex(declaration_raw)
        body["declaration_schema"] = declaration["schema"]
        for dependency in declaration.get("dependencies", []):
            body["dependencies"].append({key: dependency[key] for key in ("id", "repository", "commit", "env")})
            if not head_present(dependencies.get(dependency["id"]), dependency["commit"]):
                raise Refused("FAIL_CLOSED", "REQUIRED_CHECK_DEPENDENCY_NOT_SUPPLIED",
                              "EVERY_DECLARED_DEPENDENCY_IS_SUPPLIED_AT_ITS_COMMIT",
                              "--dependency " + dependency["id"] + "=<git checkout holding " + dependency["repository"]
                              + " " + dependency["commit"] + ">", "re-run with the dependency supplied",
                              "dependency " + dependency["id"] + " not supplied at " + dependency["commit"])
        first = run_set(checkout, head, declaration, dependencies, work / "run")
        body["checks"] = first
        second = run_set(checkout, head, declaration, dependencies, work / "run")
        differing = [a["id"] for a, b in zip(first, second) if a != b]
        body["checks"] = bind(first, second)

        def ids(predicate) -> list[str]:
            return [c["id"] for c in first if predicate(c)]
        incomplete = sorted({c["id"] for c in first + second if c["outcome"] == "DID_NOT_COMPLETE"})
        if incomplete:
            raise Refused("FAIL_CLOSED", "REQUIRED_CHECK_DID_NOT_COMPLETE", "EVERY_DECLARED_CHECK_COMPLETES_OFFLINE",
                          "each declared check must finish within " + str(CHECK_TIMEOUT_S) + "s offline: "
                          + ", ".join(incomplete), "re-run; repair the check at a new head if it hangs",
                          "did not complete: " + ", ".join(incomplete))
        clock = sorted({c["id"] for c in first + second if c["clock_reads"]})
        if clock:
            raise Refused("DENY", "REQUIRED_CHECK_READS_THE_CLOCK", "EVERY_DECLARED_CHECK_IS_A_FUNCTION_OF_THE_HEAD",
                          "remove the wall-clock read from " + ", ".join(clock)
                          + " (time is a supplied input only), or stop declaring it as required",
                          "repair at a new head and re-run", "wall-clock reads in: " + ", ".join(clock))
        network = sorted({c["id"] for c in first + second if c["network_reads"]})
        if network:
            raise Refused("DENY", "REQUIRED_CHECK_READS_THE_NETWORK", "EVERY_DECLARED_CHECK_RUNS_OFFLINE",
                          "remove the network access from " + ", ".join(network), "repair at a new head and re-run",
                          "network attempts in: " + ", ".join(network))
        if differing:
            raise Refused("DENY", "REQUIRED_CHECK_OUTPUT_DIFFERS_ACROSS_TWO_RUNS",
                          "EVERY_DECLARED_CHECK_IS_A_FUNCTION_OF_THE_HEAD",
                          "make " + ", ".join(differing) + " print the same bytes and exit code for the same head",
                          "repair at a new head and re-run", "differs across two runs: " + ", ".join(differing))
        failed = ids(lambda c: c["outcome"] != c["expected_outcome"])
        if failed:
            raise Refused("DENY", "REQUIRED_CHECK_FAILED_AT_HEAD", "EVERY_DECLARED_CHECK_PASSES_AT_THE_HEAD",
                          "make " + ", ".join(failed) + " pass at a new head", "repair at a new head and re-run",
                          "failed: " + ", ".join(failed))
        body["deterministic_across_runs"] = 2
        body["disposition"] = "ALLOW"
    except Refused as refusal:
        body["disposition"] = refusal.disposition
        body["detail"] = refusal.detail
        body.update(refusal.fields)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {**body, "receipt_sha256": "sha256:" + sha256_hex(canon(body))}


def render(receipt: dict[str, Any]) -> bytes:
    return canon(receipt) + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--dependency", action="append", default=[], metavar="ID=CHECKOUT")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    dependencies = {}
    for item in args.dependency:
        name, _, path = item.partition("=")
        dependencies[name] = Path(path)
    receipt = verify(args.input, args.checkout, dependencies)
    data = render(receipt)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
    return 0 if receipt["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
