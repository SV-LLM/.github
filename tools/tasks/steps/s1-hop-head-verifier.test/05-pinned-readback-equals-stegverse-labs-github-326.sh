set -euo pipefail
rb=2ba0e329c224c94863dac15de3f8011f777cb34f
git -C "$RUNNER_TEMP/labs" fetch -q --no-tags --depth 1 https://github.com/StegVerse-Labs/.github.git "$rb"
test "$(git -C "$RUNNER_TEMP/labs" rev-parse "$rb:resident-runtime/sv_change_base_state_readback.py")" = 2c730142254b78a5b9e1c05566fe6f5111b7d571
test "$(git hash-object sandbox/s1_pins/sv_change_base_state_readback.py)" = 2c730142254b78a5b9e1c05566fe6f5111b7d571
git -C "$RUNNER_TEMP/labs" show "$rb:resident-runtime/sv_change_base_state_readback.py" | cmp - sandbox/s1_pins/sv_change_base_state_readback.py
python3 - <<'PY'
import ast, hashlib, sys
sys.path.insert(0, "sandbox")
import s1_supplied_epoch_binder as eb
def seg(path):
    src = open(path).read()
    return {n.name: hashlib.sha256(ast.get_source_segment(src, n).encode()).hexdigest()
            for n in ast.parse(src).body if isinstance(n, ast.FunctionDef)}
theirs, mine = seg("sandbox/s1_pins/sv_change_base_state_readback.py"), seg("sandbox/s1_supplied_epoch_binder.py")
for name in ("canon", "seal"):
    assert theirs[name] == mine[name] == eb.READBACK_SEGMENT_SHA256[name], name
assert mine["supplied_epoch_failure"] == eb.SHARED_RULE_SHA256
print("#3266 canon/seal and the 726248a5 rule byte-identical at", eb.READBACK_PIN_COMMIT)
PY
