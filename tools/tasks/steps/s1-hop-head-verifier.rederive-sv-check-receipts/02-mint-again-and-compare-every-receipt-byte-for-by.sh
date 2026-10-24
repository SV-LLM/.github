set -euo pipefail
in="sandbox/s1-sv-check-inputs/$INPUT.json"
record=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["sv_change"]; print(s["file"] if s["repository"] == "OUT_OF_TREE" else "")' "$in")
if [ -n "$record" ] && [ ! -f "$record" ]; then
  # The record is out of tree (box-only): the bundle cannot be re-minted here. Re-derive its change_id from the
  # fetched head instead and require it to be the committed one; the receipts are re-checked by the test job.
  b="evidence/sv-check-receipts/$INPUT/bundle.json"
  python3 -c 'import json,sys; b=json.load(open(sys.argv[1])); sv=b["sv_change"]; json.dump({"target_repository": b["repository"], "base_ref": sv["base_ref"], "projection": {"base_sha": sv["base_sha"]}}, open(sys.argv[2], "w"))' "$b" "$RUNNER_TEMP/identity.json"
  derived=$(python3 -P sandbox/s1_sv_check_receipts.py derive-change-id --checkout "$RUNNER_TEMP/head" \
    --head "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head_sha"])' "$in")" --record-identity "$RUNNER_TEMP/identity.json")
  python3 - "$b" "$in" "$derived" <<'PY'
import json, sys
b, i = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
assert b["sv_change"]["sha256"] == i["sv_change"]["sha256"], "bundle is not over the pinned record"
assert b["sv_change"]["change_id"] == b["sv_change"]["derived_change_id"] == sys.argv[3], (b["sv_change"], sys.argv[3])
print("record out of tree; change_id", sys.argv[3], "derived from the fetched head equals the committed bundle's")
PY
  exit 0
fi
code=0
python3 -P sandbox/s1_sv_check_receipts.py mint --input "sandbox/s1-sv-check-inputs/$INPUT.json" \
  --checkout "$RUNNER_TEMP/head" --dependency "labs-row=$RUNNER_TEMP/labs" --out-dir "$RUNNER_TEMP/out" || code=$?
echo "minter exit $code (0 only when all six are ALLOW; the committed receipts decide)"
python3 -c 'import json,sys; b=json.load(open(sys.argv[1])); print("bundle", b["disposition"], b.get("failure_code"), "hb_epoch", b.get("hb_epoch"))' "$RUNNER_TEMP/out/bundle.json"
diff -r "evidence/sv-check-receipts/$INPUT" "$RUNNER_TEMP/out"
for f in "$RUNNER_TEMP"/out/*.json; do
  python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(sys.argv[1].rsplit("/",1)[1], r.get("disposition"), r.get("failure_code"))' "$f"
done
echo "re-minted receipts are byte-identical to evidence/sv-check-receipts/$INPUT"
