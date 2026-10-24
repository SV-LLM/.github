set -euo pipefail
committed="evidence/s1-hop-head/$INPUT.json"
code=0
python3 -P sandbox/s1_hop_head_verifier.py --input "sandbox/s1-inputs/$INPUT.json" \
  --checkout "$RUNNER_TEMP/head" --out "$RUNNER_TEMP/receipt.json" || code=$?
echo "verifier exit $code (0 only for ALLOW; the committed receipt decides the expected disposition)"
python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r["disposition"], r.get("failure_code"), r["receipt_sha256"])' "$RUNNER_TEMP/receipt.json"
cmp "$committed" "$RUNNER_TEMP/receipt.json"
echo "re-derived receipt is byte-identical to $committed"
