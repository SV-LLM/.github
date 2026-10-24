set -euo pipefail
code=0
python3 -P sandbox/s1_nwi_s0_exit_gate.py evaluate --input "sandbox/s1-stage-evaluations/$EVALUATION.json" \
  --checkout "$RUNNER_TEMP/labs" --p1 "$RUNNER_TEMP/labs" --out-dir "$RUNNER_TEMP/out" || code=$?
echo "evaluator exit $code"
python3 -c 'import json,sys; e=json.load(open(sys.argv[1])); print(e["disposition"], e.get("failure_code"), e["evaluation_subject_digest"], e["receipts"])' "$RUNNER_TEMP/out/evaluation.json"
diff -r "evidence/stage-evaluations/$EVALUATION" "$RUNNER_TEMP/out"
