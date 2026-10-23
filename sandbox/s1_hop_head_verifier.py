#!/usr/bin/env python3
"""S1 SV-LLM sandbox: verify one SV_CHANGE head by running the one-way hop check.

Stage S1 of the SV-LLM environment (S0 types, S1 environment, S2 verify-only,
S3 bounded solving, S4 native). The input is a manifest-declared SV_CHANGE: a
repository, a pull request, an exact 40-hex head commit, the check to run
(``intr-destination-hop/hop``) and a supplied ``hb_epoch``. The verifier

1. materializes the exact head tree from a local git checkout
   (``git archive <head>``; the working tree is never read),
2. runs that head's own ``resident-runtime/intr_hop.py`` through the three
   phases of the ``hop`` job (send, receive, close) and reads each phase back,
   against a destination fixture stamped from the same head and temporary
   ledgers inside the sandbox,
3. emits one canonical-JSON receipt bound to the head commit and tree, with
   the disposition ``ALLOW`` (the hop ran and passed), ``DENY`` (the hop ran
   and the head's code refused or did not close) or ``FAIL_CLOSED`` (the
   check could not be run). Every non-ALLOW carries the six fields.

No clock is read: time is the supplied ``hb_epoch`` (phases at epoch, +1, +2,
as the workflow forwards), checked with the shared ``supplied_epoch_failure``
vendored byte-identical below. Ledger commits use a fixed date. Nothing is
dispatched, nothing is fetched, no credential is passed to the phases, and no
ledger outside the sandbox is appended. The receipt is admission-input
evidence (EXACT_HEAD_CHECK_NOT_RUN), not an authentic organization-ledger
receipt. Standard library only. The same input gives the same bytes.
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

RECEIPT_SCHEMA = "stegverse.sv-llm.s1-hop-head-verification-receipt/v1"
INPUT_SCHEMA = "stegverse.sv-change.s1-verification-input/v1"
INPUT_TYPE = "SV_CHANGE"
# The SV_CHANGE type itself is defined by P1 (StegVerse-org/.github#163, S0).
# This is the S1 verification projection of it; no other field is read.
INPUT_TYPE_DEFINITION = "PENDING_P1_S0_SV_CHANGE (StegVerse-org/.github#163)"
CHECK = "intr-destination-hop/hop"
WORKFLOW = ".github/workflows/intr-destination-hop.yml"
MODULE = "resident-runtime/intr_hop.py"
SERVICES = "org-boundary/registry/services.json"
REPO_CONTRACT = ".stegverse/transition-ledger/contract.json"
STAMPED = (SERVICES, "org-runtime/interlock-intr.json", REPO_CONTRACT,
           ".stegverse/transition-ledger/org-contract.json")
FIXTURE = "Hop-Peer-Fixture"
FIXTURE_SLUG = "hop-peer-fixture"
LEDGER_REF = "refs/stegverse/organization-ledger"
FIXED_GIT_DATE = "@0 +0000"
PHASE_TIMEOUT_S = 180
OWNING_EXISTING_GOAL = "StegVerse-org/.github#162 / INTERLOCK-INTR-RUNTIME-INDEPENDENT-PROTOCOL-001"
RETRY_ENTRYPOINT = "sandbox/s1_hop_head_verifier.py --input <sv-change.json> --checkout <git checkout>"
NON_ALLOW_FIELDS = ("failure_code", "failed_predicate", "required_evidence_or_repair",
                    "retry_entrypoint", "owning_existing_goal", "next_attempt")
EVIDENCE_ROLE = "ADMISSION_INPUT_EVIDENCE_ONLY"
EVIDENCE_NOTE = ("Evidence for the merge-admission transition (clears EXACT_HEAD_CHECK_NOT_RUN for this exact "
                 "head). Not an authentic organization-ledger receipt: every hop receipt it names was written "
                 "to a temporary sandbox ledger against a fabricated destination fixture.")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
SHARED_RULE_SHA256 = "726248a585904b52cfe2eec1754e7ce582f67d6b501bd664bb7bee80bce9b7ef"


class Refused(Exception):
    def __init__(self, disposition: str, failure_code: str, failed_predicate: str, repair: str,
                 next_attempt: str, detail: str = "") -> None:
        super().__init__(failure_code + ": " + detail)
        self.disposition = disposition
        self.fields = {
            "failure_code": failure_code, "failed_predicate": failed_predicate,
            "required_evidence_or_repair": repair, "retry_entrypoint": RETRY_ENTRYPOINT,
            "owning_existing_goal": OWNING_EXISTING_GOAL, "next_attempt": next_attempt,
        }
        self.detail = detail


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- shared rule, vendored byte-identical from StegVerse-Labs/.github
# org-kernel/kernel.py (sha256 of the segment: SHARED_RULE_SHA256) ---------
def supplied_epoch_failure(hb_epoch: Any, reference: Any = None) -> tuple[str, str] | None:
    """The shared supplied-epoch rule (SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH).

    Byte-identical in StegVerse-org/.github#185 and StegVerse-Labs/.github#3212
    and #3213. `hb_epoch` absent (None) is HB_EPOCH_NOT_SUPPLIED. Otherwise it
    must be ASCII [0-9]+ only -- an int is read as its decimal text; a bool, a
    float or anything coerced ('+33', ' 33', '3_3', '33.0') is refused -- with
    integer value >= 32 (the HB32 anchor). `reference`, the carrier frame's
    heartbeat reference when there is one, must be an object, and a
    `derived_from_clock` it carries must be exactly false. Any failure is
    HB_EPOCH_INVALID. Returns (failure_code, detail), or None when the epoch is
    supplied. No clock is read.
    """
    if reference is not None and not isinstance(reference, dict):
        return "HB_EPOCH_INVALID", "the carrier's heartbeat reference is not an object"
    if hb_epoch is None:
        return "HB_EPOCH_NOT_SUPPLIED", "no hb_epoch was supplied and no clock is read"
    if isinstance(hb_epoch, bool):
        text = None
    elif isinstance(hb_epoch, int):
        text = str(hb_epoch)
    elif isinstance(hb_epoch, str):
        text = hb_epoch
    else:
        text = None
    if text is None or not text.isascii() or not text.isdigit():
        return "HB_EPOCH_INVALID", "hb_epoch " + repr(hb_epoch) + " is not ASCII [0-9]+"
    if int(text) < 32:
        return "HB_EPOCH_INVALID", "hb_epoch " + text + " is below the HB32 anchor (32)"
    if reference is not None and "derived_from_clock" in reference \
            and reference["derived_from_clock"] is not False:
        return "HB_EPOCH_INVALID", ("the carrier's derived_from_clock is not exactly false; "
                                    "a clock-derived epoch is not a supplied one")
    return None


def read_input(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refused("FAIL_CLOSED", "S1_INPUT_NOT_READABLE", "S1_INPUT_IS_A_READABLE_JSON_SV_CHANGE",
                      "a UTF-8 JSON file declaring the SV_CHANGE to verify", "re-run with a readable input file",
                      type(exc).__name__) from None
    return document, raw


def validate_input(document: Any) -> dict[str, Any]:
    def bad(detail: str) -> Refused:
        return Refused("FAIL_CLOSED", "S1_INPUT_NOT_A_DECLARED_SV_CHANGE", "S1_INPUT_DECLARES_ONE_SV_CHANGE_HEAD",
                       "an input with schema " + INPUT_SCHEMA + ", type " + INPUT_TYPE + ", repository <owner>/<repo>, "
                       "pull_request <int>, head_sha <40 lowercase hex>, check " + CHECK + " and hb_epoch",
                       "re-run with the corrected manifest; nothing was run", detail)
    if not isinstance(document, dict):
        raise bad("input is not an object")
    if document.get("schema") != INPUT_SCHEMA:
        raise bad("schema " + repr(document.get("schema")))
    if document.get("type") != INPUT_TYPE:
        raise bad("type " + repr(document.get("type")))
    repository = document.get("repository")
    if not isinstance(repository, str) or not REPOSITORY.match(repository):
        raise bad("repository " + repr(repository))
    number = document.get("pull_request")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise bad("pull_request " + repr(number))
    head = document.get("head_sha")
    if not isinstance(head, str) or not HEX40.match(head):
        raise bad("head_sha " + repr(head))
    if document.get("check") != CHECK:
        raise bad("check " + repr(document.get("check")))
    if "hb_epoch" not in document:
        document = {**document, "hb_epoch": None}
    failure = supplied_epoch_failure(document.get("hb_epoch"))
    if failure is not None:
        code, detail = failure
        raise Refused("FAIL_CLOSED", code, "SUBMISSION_CARRIES_THE_SUPPLIED_HB_EPOCH",
                      "a supplied hb_epoch: ASCII [0-9]+ (or an int), value >= 32 (the HB32 anchor); no clock is read",
                      "re-run with a supplied hb_epoch; nothing was run", detail)
    return {"repository": repository, "pull_request": number, "head_sha": head, "check": CHECK,
            "hb_epoch": int(str(document["hb_epoch"]))}


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, env=_base_env(None))


def materialize_head(checkout: Path, head: str, dest: Path) -> str:
    """Extract exactly ``head``'s tree into ``dest``; return the tree id."""
    def missing(detail: str) -> Refused:
        return Refused("FAIL_CLOSED", "HEAD_NOT_MATERIALIZED", "THE_DECLARED_HEAD_IS_PRESENT_IN_THE_CHECKOUT",
                       "a local git checkout that holds commit " + head + " (fetch it; the verifier itself never fetches)",
                       "re-run once the checkout holds the declared head", detail)
    if not (checkout / ".git").exists() and _git(checkout, "rev-parse", "--git-dir").returncode != 0:
        raise missing("not a git checkout")
    resolved = _git(checkout, "rev-parse", "--verify", "--quiet", head + "^{commit}")
    if resolved.returncode != 0 or resolved.stdout.decode().strip() != head:
        raise missing("commit not present")
    tree = _git(checkout, "rev-parse", head + "^{tree}").stdout.decode().strip()
    archive = _git(checkout, "archive", "--format=tar", head)
    if archive.returncode != 0:
        raise missing("git archive failed")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        for member in tar.getmembers():
            if member.issym() or member.islnk() or member.name.startswith("/") or ".." in Path(member.name).parts:
                continue
            if hasattr(tarfile, "data_filter"):
                tar.extract(member, dest, filter="data")
            else:
                tar.extract(member, dest)
    return tree


def require_hop_check(root: Path) -> dict[str, str]:
    absent = [relative for relative in (MODULE, WORKFLOW, SERVICES, REPO_CONTRACT) if not (root / relative).is_file()]
    workflow = (root / WORKFLOW).read_text(encoding="utf-8") if not absent else ""
    if not absent and not re.search(r"(?m)^  hop:\s*$", workflow):
        absent.append(WORKFLOW + " jobs.hop")
    if absent:
        raise Refused("FAIL_CLOSED", "HOP_CHECK_ABSENT_AT_HEAD", "THE_HEAD_CARRIES_THE_ONE_WAY_HOP_CHECK",
                      "the head must carry " + ", ".join(absent),
                      "re-run against a head that carries the hop check", ", ".join(absent))
    return {"module_sha256": sha256_hex((root / MODULE).read_bytes()),
            "workflow_sha256": sha256_hex((root / WORKFLOW).read_bytes())}


def organization_of(root: Path) -> str:
    return json.loads((root / SERVICES).read_text(encoding="utf-8"))["organization"]


def slug_of(organization: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in organization).strip("-")


def stamp_fixture(head_root: Path, dest: Path) -> Path:
    """The destination: a copy of the same head with its advertisement re-stamped as the fixture peer."""
    organization = organization_of(head_root)
    shutil.copytree(head_root, dest)
    for relative in STAMPED:
        path = dest / relative
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            text = text.replace(organization, FIXTURE).replace(slug_of(organization) + ".", FIXTURE_SLUG + ".")
            path.write_text(text, encoding="utf-8")
    return dest


def _base_env(home: Path | None) -> dict[str, str]:
    """No inherited credentials or STEGVERSE_* ledger locations; a fixed git identity and date."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_NAME": "sv-llm-s1-sandbox", "GIT_AUTHOR_EMAIL": "s1-sandbox@example.invalid",
           "GIT_COMMITTER_NAME": "sv-llm-s1-sandbox", "GIT_COMMITTER_EMAIL": "s1-sandbox@example.invalid",
           "GIT_AUTHOR_DATE": FIXED_GIT_DATE, "GIT_COMMITTER_DATE": FIXED_GIT_DATE, "TZ": "UTC"}
    if home is not None:
        env["HOME"] = str(home)
    return env


class Side:
    def __init__(self, root: Path, home: Path) -> None:
        self.root = root
        self.home = home
        self.ledger = home / "ledger"
        home.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.ledger)], check=True, env=_base_env(home))
        contract = json.loads((root / REPO_CONTRACT).read_text(encoding="utf-8"))
        self.namespace = contract["repository_ledger_location"]["namespace"]

    def env(self) -> dict[str, str]:
        env = _base_env(self.home)
        env.update({"STEGVERSE_ORG_LEDGER_ROOT": "git+%s#%s" % (self.ledger, LEDGER_REF),
                    "STEGVERSE_ORG_LEDGER_GIT_DIR": str(self.ledger / ".git"),
                    "STEGVERSE_REPO_LEDGER_ROOT": "git+%s#%s:%s" % (self.ledger, LEDGER_REF, self.namespace)})
        return env

    def run(self, work: Path, name: str, *args: str) -> tuple[int | None, dict[str, Any] | None]:
        out = work / (name + ".json")
        try:
            completed = subprocess.run([sys.executable, "-P", str(self.root / MODULE), *args, "--out", str(out)],
                                       cwd=self.root, env=self.env(), capture_output=True, timeout=PHASE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, None
        try:
            return completed.returncode, json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return completed.returncode, None


_PHASE_KEYS = ("disposition", "packet_id", "communication_id", "hb_epoch", "frame_sha256",
               "repository_receipt_sha256", "organization_receipt_sha256", "transition_class",
               "response_message_class", "closed", "failure_code", "failed_predicate")


def _phase_summary(phase: str, code: int | None, result: dict[str, Any] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {"phase": phase, "exit_code": code}
    for key in _PHASE_KEYS:
        if isinstance(result, dict) and key in result:
            summary[key] = result[key]
    return summary


def run_hop(head_root: Path, work: Path, inputs: dict[str, Any], phases: list[dict[str, Any]]) -> dict[str, Side]:
    """send -> receive -> close -> readback, as the hop job runs them, inside the sandbox."""
    work.mkdir(parents=True, exist_ok=True)
    peer_root = stamp_fixture(head_root, work / "peer")
    sender = Side(head_root, work / "sender")
    destination = Side(peer_root, work / "destination")
    origin_slug = slug_of(organization_of(head_root))
    epoch = inputs["hb_epoch"]
    cid = "s1-verify:%s:%s:%s" % (origin_slug, FIXTURE_SLUG, inputs["head_sha"][:12])

    def step(side: Side, phase: str, *args: str) -> dict[str, Any]:
        code, result = side.run(work, phase, phase, *args)
        summary = _phase_summary(phase, code, result)
        phases.append(summary)
        if result is None:
            raise Refused("FAIL_CLOSED", "HOP_CHECK_DID_NOT_COMPLETE", "THE_HOP_PHASE_RAN_AND_RETURNED_A_RESULT",
                          "the head's " + MODULE + " " + phase + " must run to a JSON result within "
                          + str(PHASE_TIMEOUT_S) + "s in the sandbox",
                          "re-run the verifier after the phase completes at this head", phase)
        if code != 0 or result.get("disposition") != "ALLOW":
            raise Refused("DENY", "HOP_CHECK_REFUSED_AT_HEAD", "THE_HOP_CHECK_PASSES_AT_THE_EXACT_HEAD",
                          "a head whose " + phase + " phase is ALLOW (it returned " + repr(result.get("failure_code")
                          or result.get("disposition")) + ")",
                          "repair the head and re-run the verifier at the new head", phase)
        return result

    def frame(text: str, name: str) -> str:
        path = work / (name + ".b64")
        path.write_text(text, encoding="ascii")
        return str(path)

    sent = step(sender, "send", "--destination-slug", FIXTURE_SLUG, "--communication-id", cid,
                "--hb-epoch", str(epoch), "--peer-root", str(peer_root))
    arrived = step(destination, "receive", "--frame-file", frame(sent.get("frame", ""), "sent"),
                   "--origin-slug", origin_slug, "--hb-epoch", str(epoch + 1))
    closed = step(sender, "close", "--frame-file", frame(arrived.get("frame", ""), "arrived"),
                  "--destination-slug", FIXTURE_SLUG, "--communication-id", cid, "--hb-epoch", str(epoch + 2))
    if closed.get("closed") is not True:
        raise Refused("DENY", "HOP_CHECK_REFUSED_AT_HEAD", "THE_HOP_CHECK_PASSES_AT_THE_EXACT_HEAD",
                      "a closure recorded for the hop's communication_id", "repair the head and re-run", "close")
    for side, name, result in ((sender, "send", sent), (destination, "receive", arrived), (sender, "close", closed)):
        result_path = work / (name + "-result.json")
        result_path.write_text(json.dumps(result), encoding="utf-8")
        code, read = side.run(work, "readback-" + name, "readback", "--location",
                              "git+%s#%s" % (side.ledger, LEDGER_REF), "--repository-namespace", side.namespace,
                              "--result", str(result_path))
        failed = (read or {}).get("failed_predicates")
        phases.append({"phase": "readback-" + name, "exit_code": code, "failed_predicates": failed})
        if read is None:
            raise Refused("FAIL_CLOSED", "HOP_CHECK_DID_NOT_COMPLETE", "THE_HOP_PHASE_RAN_AND_RETURNED_A_RESULT",
                          "the head's readback of the " + name + " receipts must return a JSON result",
                          "re-run the verifier after the readback completes at this head", "readback-" + name)
        if code != 0 or failed != []:
            raise Refused("DENY", "HOP_CHECK_REFUSED_AT_HEAD", "THE_HOP_RECEIPTS_READ_BACK_AT_THE_EXACT_HEAD",
                          "the " + name + " receipts read back with no failed predicates (got " + repr(failed) + ")",
                          "repair the head and re-run the verifier at the new head", "readback-" + name)
    return {"send": sender, "receive": destination, "close": sender}


NONDETERMINISTIC = "NONDETERMINISTIC_ACROSS_TWO_SANDBOX_RUNS"
_DIGEST_KEYS = ("repository_receipt_sha256", "organization_receipt_sha256")


def _receipt_blob(side: Side, digest: Any, repository: bool) -> Any:
    if not isinstance(digest, str) or ":" not in digest:
        return None
    key = (side.namespace + "/" if repository else "") + "receipts/" + digest.split(":", 1)[1] + ".json"
    shown = subprocess.run(["git", "-C", str(side.ledger), "cat-file", "blob", LEDGER_REF + ":" + key],
                           capture_output=True, env=_base_env(side.home))
    try:
        return json.loads(shown.stdout) if shown.returncode == 0 else None
    except json.JSONDecodeError:
        return None


def _differing_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        found: list[str] = []
        for key in sorted(set(left) | set(right)):
            found.extend(_differing_paths(left.get(key), right.get(key), path + "/" + key))
        return found
    return [] if left == right else [path or "/"]


def compare_runs(first: list[dict[str, Any]], second: list[dict[str, Any]],
                 sides_first: dict[str, Side], sides_second: dict[str, Side]) -> tuple[list[dict[str, Any]], list[str]]:
    """The phases with every value that differs between two identical runs masked, and the receipt fields that differ.

    Time is supplied, so the same head and inputs must write the same receipts.
    A field that differs between two runs depends on something not supplied
    (a clock, a random id, a path). Digests that cover only such fields differ
    too; the receipt-body paths name the cause. Volatile fields (``observed_at``,
    ``recorded_at``) are listed whichever receipt layer carries them.
    """
    masked: list[dict[str, Any]] = []
    fields: set[str] = set()
    for left, right in zip(first, second):
        entry = {key: (value if right.get(key) == value else NONDETERMINISTIC) for key, value in left.items()}
        masked.append(entry)
        phase = left.get("phase")
        if phase in sides_first and phase in sides_second:
            for key in _DIGEST_KEYS:
                if left.get(key) != right.get(key):
                    layer = "repository" if key.startswith("repository") else "organization"
                    a = _receipt_blob(sides_first[phase], left.get(key), layer == "repository")
                    b = _receipt_blob(sides_second[phase], right.get(key), layer == "repository")
                    for found in _differing_paths(a, b):
                        if found not in ("/receipt_sha256", "/previous_receipt_sha256", "/repo_receipt_sha256",
                                         "/source_transition_sha256"):
                            fields.add(layer + "_receipt" + found)
    if len(first) != len(second):
        fields.add("phase_count")
    return masked, sorted(fields)


def verifier_sha256() -> str:
    return sha256_hex(Path(__file__).read_bytes())


def verify(input_path: Path, checkout: Path | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "stage": "S1", "environment": "SV_LLM_SANDBOX_LOCAL_OFFLINE",
        "input_type": INPUT_TYPE, "input_type_definition": INPUT_TYPE_DEFINITION, "input_schema": INPUT_SCHEMA,
        "check": CHECK, "evidence_role": EVIDENCE_ROLE, "evidence_note": EVIDENCE_NOTE,
        "authentic_ledger_receipt": False, "authority_effect": "NONE", "time_source": "SUPPLIED_HB_EPOCH",
        "clock_read": False, "dispatched": False, "network_read": False, "credentials_passed": False,
        "ledger_appended_outside_sandbox": False, "verifier": {"path": "sandbox/s1_hop_head_verifier.py",
                                                               "sha256": verifier_sha256()},
        "input_sha256": None, "repository": None, "pull_request": None, "head_sha": None, "head_tree": None,
        "hb_epoch": None, "hop_check": None, "phases": [],
    }
    work = Path(tempfile.mkdtemp(prefix="sv-llm-s1-"))
    try:
        document, raw = read_input(input_path)
        body["input_sha256"] = sha256_hex(raw)
        inputs = validate_input(document)
        body.update({key: inputs[key] for key in ("repository", "pull_request", "head_sha", "hb_epoch")})
        if checkout is None:
            raise Refused("FAIL_CLOSED", "HEAD_NOT_MATERIALIZED", "THE_DECLARED_HEAD_IS_PRESENT_IN_THE_CHECKOUT",
                          "--checkout naming a local git checkout that holds the declared head",
                          "re-run with --checkout", "no checkout")
        head_root = work / "head"
        head_root.mkdir()
        body["head_tree"] = materialize_head(checkout, inputs["head_sha"], head_root)
        body["hop_check"] = {"workflow": WORKFLOW, "job": "hop", "module": MODULE, **require_hop_check(head_root),
                             "destination": FIXTURE_SLUG + ".intr-destination (fabricated fixture from the same head)",
                             "phase_epochs": [inputs["hb_epoch"], inputs["hb_epoch"] + 1, inputs["hb_epoch"] + 2]}
        first: list[dict[str, Any]] = []
        second: list[dict[str, Any]] = []
        try:
            sides_first = run_hop(head_root, work / "run-1", inputs, first)
        finally:
            body["phases"] = first
        sides_second = run_hop(head_root, work / "run-2", inputs, second)
        if first != second:
            body["phases"], fields = compare_runs(first, second, sides_first, sides_second)
            body["nondeterministic_receipt_fields"] = fields
            raise Refused("DENY", "HOP_RECEIPTS_DEPEND_ON_AN_UNSUPPLIED_INPUT",
                          "THE_HOP_RECEIPTS_ARE_A_FUNCTION_OF_THE_SUPPLIED_INPUTS",
                          "the head's hop must write the same receipts for the same head and supplied hb_epoch; "
                          "remove the clock read or other unsupplied value behind " + (", ".join(fields) or "the digests")
                          + " (time is the supplied hb_epoch only)",
                          "repair the head's receipt writer and re-run the verifier at the new head",
                          "two sandbox runs of the same head wrote different receipts")
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
    """The receipt's bytes: canonical JSON plus a trailing newline."""
    return canon(receipt) + b"\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True, help="SV_CHANGE S1 verification input (JSON)")
    parser.add_argument("--checkout", type=Path, help="local git checkout holding the declared head")
    parser.add_argument("--out", type=Path, help="write the receipt here (default: stdout)")
    args = parser.parse_args(argv)
    receipt = verify(args.input, args.checkout)
    data = render(receipt)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
    return 0 if receipt["disposition"] == "ALLOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
