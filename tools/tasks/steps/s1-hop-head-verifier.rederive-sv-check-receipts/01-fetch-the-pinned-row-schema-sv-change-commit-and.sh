set -euo pipefail
in="sandbox/s1-sv-check-inputs/$INPUT.json"
pin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["required_checks_row"]["commit"])' "$in")
head=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head_sha"])' "$in")
git init -q "$RUNNER_TEMP/labs"
git -C "$RUNNER_TEMP/labs" fetch -q --no-tags --depth 1 https://github.com/StegVerse-Labs/.github.git "$pin"
git init -q "$RUNNER_TEMP/head"
if [ -n "$REPOSITORY" ]; then
  # full history: the row's {base_commit} binding must be an ancestor present in the clone
  git -C "$RUNNER_TEMP/head" fetch -q --no-tags "https://github.com/$REPOSITORY.git" "$head"
  test "$(git -C "$RUNNER_TEMP/head" rev-parse FETCH_HEAD)" = "$head"
  base=$(python3 -c 'import json,sys; print((json.load(open(sys.argv[1])).get("base_commit") or {}).get("sha",""))' "$in")
  if [ -n "$base" ]; then git -C "$RUNNER_TEMP/head" merge-base --is-ancestor "$base" "$head"; echo "base_commit $base is an ancestor of $head"; fi
fi
