set -euo pipefail
committed="evidence/s1-required-checks/$INPUT.json"
code=0
python3 -P sandbox/s1_required_checks_verifier.py --input "sandbox/s1-required-checks-inputs/$INPUT.json" \
  --checkout "$RUNNER_TEMP/head" $(cat "$RUNNER_TEMP/deps.args") --out "$RUNNER_TEMP/receipt.json" || code=$?
echo "verifier exit $code (0 only for ALLOW; the committed receipt decides the expected disposition)"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r["disposition"], r.get("failure_code"), r["receipt_sha256"])' "$RUNNER_TEMP/receipt.json"
cmp "$committed" "$RUNNER_TEMP/receipt.json" || { diff <(python3 -m json.tool "$committed") <(python3 -m json.tool "$RUNNER_TEMP/receipt.json") || true; exit 1; }
echo "re-derived receipt is byte-identical to $committed"
