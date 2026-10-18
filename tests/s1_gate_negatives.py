"""nwi-s0-exit-gate negatives and invariance (argv[1] = a local StegVerse-Labs/.github clone holding the contract pin
and the evaluated commit). Each case is a STAGE_GATE evaluation of a temporary local commit or input; nothing is
pushed, nothing is appended. Run by CI's stage-evaluation rederive job and locally."""
import copy, json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "sandbox")
import s1_nwi_s0_exit_gate as g
import s1_sv_check_receipts as m

LABS = Path(sys.argv[1]).resolve()
INPUT = Path("sandbox/s1-stage-evaluations/NWI-S0-StegVerse-Labs-7898cedb.json")
BASE = json.loads(INPUT.read_text())
tmp = Path(tempfile.mkdtemp(prefix="s1gate-neg-"))
n = 0


def run(doc, checkout=LABS):
    global n
    n += 1
    path = tmp / ("in-%d.json" % n)
    path.write_text(json.dumps(doc))
    return g.evaluate(path, checkout, LABS)


def commit_on(base_commit, edits):
    """A local clone with one commit on top of base_commit applying edits {path: bytes|callable(bytes)->bytes}."""
    repo = tmp / ("repo-%d" % (n + 1))
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "PATH": "/usr/bin:/bin"}
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(LABS), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", base_commit], check=True)
    for p, e in edits.items():
        f = repo / p
        f.write_bytes(e(f.read_bytes()) if callable(e) else e)
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "negative"], check=True, env=env)
    return repo, subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def refused(out, receipts, code):
    assert receipts == {}, (code, sorted(receipts))
    assert out["disposition"] == "FAIL_CLOSED" and out["failure_code"] == code, (code, out.get("failure_code"), out.get("detail"))
    assert all(out.get(k) for k in m.SIX_FIELDS), out


# the committed subject: ALLOW, three receipts, and the same subject gives the same digest and bytes
a, ra = run(BASE)
b, rb = run(copy.deepcopy(BASE))
assert a["disposition"] == "ALLOW" and sorted(ra) == ["nwi-s0-exit-gate", "schema-validate", "unit-tests"], a.get("failure_code")
assert m.render(a) == m.render(b) and {k: m.render(v) for k, v in ra.items()} == {k: m.render(v) for k, v in rb.items()}
assert {r["change_digest"] for r in ra.values()} == {a["evaluation_subject_digest"]}
assert {r["head_sha"] for r in ra.values()} == {BASE["evaluated_commit"]} and {r["hb_epoch"] for r in ra.values()} == {"469411750"}

# 1. subject unobserved
refused(*run({**BASE, "base_ref": {**BASE["base_ref"], "registry_generation": 318}}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")
refused(*run({**BASE, "evaluated_commit": "7898cedb"}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")
refused(*run({**BASE, "base_ref": {"ledger_head": BASE["base_ref"]["ledger_head"]}}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")
refused(*run({**BASE, "repository": "not a repo"}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")
# not a stage-gate evaluation: refused before anything is evaluated
refused(*run({**BASE, "trigger": "PULL_REQUEST_HEAD"}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")
refused(*run({**BASE, "stage_id": "NWI-S1"}), "STAGE_EVALUATION_SUBJECT_UNOBSERVED")

# 2. epoch unobserved: no readback, another ledger head, another repository's readback, broken seal
refused(*run({**BASE, "hb_epoch_readback": None}), "STAGE_EVIDENCE_UNOBSERVED")
refused(*run({**BASE, "base_ref": {**BASE["base_ref"], "ledger_head": "b" * 40}}), "STAGE_EVIDENCE_UNOBSERVED")
rb_body = json.loads(Path(BASE["hb_epoch_readback"]["file"]).read_text())
for name, body in (("other-repo", m.eb.seal({**rb_body, "repository": "StegVerse-org/.github"})),
                   ("broken-seal", {**rb_body, "hb_epoch": "469411751"}),
                   ("fail-closed", m.eb.seal({**rb_body, "disposition": "FAIL_CLOSED", "hb_epoch": None, "hb_epoch_source": None}))):
    f = tmp / (name + ".json")
    raw = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    f.write_bytes(raw)
    refused(*run({**BASE, "hb_epoch_readback": {"file": str(f), "sha256": "sha256:" + __import__("hashlib").sha256(raw).hexdigest()}}),
            "STAGE_EVIDENCE_UNOBSERVED")

# 3. declaration incomplete at the evaluated commit: no producers / a producer argv that is not the row's
for name, edit in (("no-producers", lambda c: c.pop("evidence_producers")),
                   ("argv", lambda c: c["evidence_producers"][0].__setitem__("offline_command", ["python3", "-c", "0"])),
                   ("cadence", lambda c: c["cadence"].__setitem__("not_per_head", False))):
    def change(raw, edit=edit):
        doc = json.loads(raw); edit(doc["exit_gate_check"]); return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    repo, head = commit_on(BASE["evaluated_commit"], {m.STAGE_GATE_MANIFEST_FILE: change})
    out, rs = run({**BASE, "evaluated_commit": head}, repo)
    refused(out, rs, "STAGE_GATE_DECLARATION_INCOMPLETE")
    assert out["detail"], name

# 4. a failing producer: a stale migration fixture fails schema-validate; the gate is FAIL_CLOSED STAGE_REGRESSION and
#    all three receipts are emitted (a failing gate receipt, once appended, is what derives the NATIVE SV_ISSUE)
repo, head = commit_on(BASE["evaluated_commit"], {"data/sv-work-items/migration/sv-issues.jsonl": lambda raw: raw + b"\n"})
out, rs = run({**BASE, "evaluated_commit": head}, repo)
assert sorted(rs) == ["nwi-s0-exit-gate", "schema-validate", "unit-tests"], (out.get("failure_code"), out.get("detail"))
assert rs["schema-validate"]["disposition"] == "FAIL_CLOSED" and rs["schema-validate"]["failure_code"] == "REQUIRED_CHECK_FAILED_AT_HEAD"
assert rs["nwi-s0-exit-gate"]["disposition"] == "FAIL_CLOSED" and rs["nwi-s0-exit-gate"]["failure_code"] == "STAGE_REGRESSION", rs["nwi-s0-exit-gate"]
assert out["evaluation_subject_digest"] != a["evaluation_subject_digest"]  # a new commit is a new evaluation
assert set(out["receipts_validated"]["results"].values()) == {"ALLOW"}  # failing receipts are still valid gate receipts
print(n, "stage evaluations: nwi-s0-exit-gate ALLOW on the committed subject (twice, byte-identical); "
      "SUBJECT_UNOBSERVED, EVIDENCE_UNOBSERVED and DECLARATION_INCOMPLETE emit nothing; a failing producer gives STAGE_REGRESSION")
