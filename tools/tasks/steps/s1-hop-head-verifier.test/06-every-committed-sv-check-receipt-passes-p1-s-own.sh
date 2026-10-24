set -euo pipefail
pin=7898cedba1400c8545cebcb463fd26deb25f7d5a
git -C "$RUNNER_TEMP/labs" show "$pin:resident-runtime/sv_work_items.py" > /dev/null
rm -rf "$RUNNER_TEMP/p1" && mkdir -p "$RUNNER_TEMP/p1"
git -C "$RUNNER_TEMP/labs" archive "$pin" | tar -x -C "$RUNNER_TEMP/p1"
python3 - "$RUNNER_TEMP/p1" <<'PY'
import glob, json, sys
sys.path.insert(0, sys.argv[1] + "/resident-runtime")
import sv_work_items as w
n = 0
for f in sorted(glob.glob("evidence/sv-check-receipts/*/*.json")):
    if f.endswith("/bundle.json"):
        continue
    w.validate_check_receipt(json.load(open(f)))
    n += 1
print(n, "committed receipts accepted by sv_work_items.validate_check_receipt")
PY
