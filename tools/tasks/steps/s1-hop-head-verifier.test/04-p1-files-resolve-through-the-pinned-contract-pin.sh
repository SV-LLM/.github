set -euo pipefail
pin=$(python3 -c 'import sys; sys.path.insert(0, "sandbox"); import s1_sv_check_receipts as m; print(m.CONTRACT_PINS["commit"])')
git init -q "$RUNNER_TEMP/labs"
git -C "$RUNNER_TEMP/labs" fetch -q --no-tags --depth 1 https://github.com/StegVerse-Labs/.github.git "$pin"
git -C "$RUNNER_TEMP/labs" show "$pin:data/sv-work-items/contract-pins.json" | cmp - sandbox/s1_pins/contract-pins.json
python3 - "$RUNNER_TEMP/labs" "$pin" <<'PY'
import hashlib, json, subprocess, sys
sys.path.insert(0, "sandbox")
import s1_sv_check_receipts as m, s1_supplied_epoch_binder as eb
labs, pin = sys.argv[1], sys.argv[2]
def show(path):
    return subprocess.run(["git", "-C", labs, "show", pin + ":" + path], check=True, capture_output=True).stdout
def blob(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
manifest = show(m.CONTRACT_PINS["file"])
assert "sha256:" + hashlib.sha256(manifest).hexdigest() == m.CONTRACT_PINS["sha256"], "contract-pins.json drifted"
entries = json.loads(manifest)["files"]
for path in m.USED_P1_FILES:  # each used file: its bytes at the pin match its manifest entry
    data = show(path)
    assert entries[path] == {"blob": blob(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}, path
    assert m.p1_blob(path) == entries[path]["blob"], path
for path, want in m.UNLISTED_P1_FILES.items():
    assert path not in entries and blob(show(path)) == want, path
for vendored, path in (("required-checks.json", m.ROW_FILE), ("sv-check-receipt.v1.schema.json", m.RECEIPT_SCHEMA_FILE),
                       ("NWI-S0.json", m.STAGE_GATE_MANIFEST_FILE), ("sv-change.v1.schema.json", "schemas/sv-change.v1.schema.json")):
    assert blob(open("sandbox/s1_pins/" + vendored, "rb").read()) == m.p1_blob(path), vendored
assert eb.P1_REFERENCE["commit"] == m.PIN_COMMIT and eb.P1_REFERENCE["blob_sha"] == m.p1_blob("resident-runtime/sv_work_items.py")
print("contract-pins", m.CONTRACT_PINS["sha256"], "resolves", len(m.USED_P1_FILES), "used P1 files at", pin)
PY
git -C "$RUNNER_TEMP/labs" show "$pin:resident-runtime/sv_work_items.py" > "$RUNNER_TEMP/sv_work_items.py"
python3 - "$RUNNER_TEMP/sv_work_items.py" <<'PY'
import ast, hashlib, sys
sys.path.insert(0, "sandbox")
import s1_sv_check_receipts as m
src = open(sys.argv[1]).read(); lines = src.split("\n")
found = {}
for n in ast.parse(src).body:
    name = getattr(n, "name", None) or (n.targets[0].id if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) else None)
    if name in m.P1_SEGMENT_SHA256:
        found[name] = hashlib.sha256("\n".join(lines[n.lineno - 1:n.end_lineno]).encode()).hexdigest()
assert found == m.P1_SEGMENT_SHA256, found
print("P1 segments byte-identical at", m.PIN_COMMIT)
PY
