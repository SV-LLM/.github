set -euo pipefail
for c in 7898cedb 978b8880; do
  test -d "evidence/stage-evaluations/NWI-S0-StegVerse-Labs-$c"
done
git -C "$RUNNER_TEMP/labs" fetch -q --no-tags https://github.com/StegVerse-Labs/.github.git 978b8880d238dc3e3a8b690c0675d8bb0e9d6985 7898cedba1400c8545cebcb463fd26deb25f7d5a
python3 -P sandbox/s1_gate_issue_derivation.py --evaluation evidence/stage-evaluations/NWI-S0-StegVerse-Labs-978b8880 \
  --evaluation evidence/stage-evaluations/NWI-S0-StegVerse-Labs-7898cedb --p1 "$RUNNER_TEMP/labs" \
  --change-bundle evidence/sv-check-receipts/StegVerse-Labs-3264-7898cedb/bundle.json --out "$RUNNER_TEMP/issue.json"
cmp "$RUNNER_TEMP/issue.json" evidence/stage-evaluations/NWI-S0-issue-derivation.json
