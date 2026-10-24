set -euo pipefail
head=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head_sha"])' "sandbox/s1-inputs/$INPUT.json")
git init -q "$RUNNER_TEMP/head"
git -C "$RUNNER_TEMP/head" fetch -q --no-tags --depth 1 "https://github.com/$REPOSITORY.git" "$head"
test "$(git -C "$RUNNER_TEMP/head" rev-parse FETCH_HEAD)" = "$head"
echo "fetched $REPOSITORY at $head"
