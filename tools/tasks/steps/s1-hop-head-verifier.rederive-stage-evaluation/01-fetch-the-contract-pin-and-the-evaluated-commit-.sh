set -euo pipefail
in="sandbox/s1-stage-evaluations/$EVALUATION.json"
pin=$(python3 -c 'import sys; sys.path.insert(0, "sandbox"); import s1_sv_check_receipts as m; print(m.CONTRACT_PINS["commit"])')
commit=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["evaluated_commit"])' "$in")
git init -q "$RUNNER_TEMP/labs"
git -C "$RUNNER_TEMP/labs" fetch -q --no-tags https://github.com/StegVerse-Labs/.github.git "$pin" "$commit"
git -C "$RUNNER_TEMP/labs" cat-file -e "$pin^{commit}"
git -C "$RUNNER_TEMP/labs" cat-file -e "$commit^{commit}"
