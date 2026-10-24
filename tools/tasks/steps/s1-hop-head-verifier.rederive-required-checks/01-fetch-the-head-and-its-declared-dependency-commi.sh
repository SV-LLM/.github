set -euo pipefail
head=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["head_sha"])' "sandbox/s1-required-checks-inputs/$INPUT.json")
git init -q "$RUNNER_TEMP/head"
git -C "$RUNNER_TEMP/head" fetch -q --no-tags --depth 1 "https://github.com/$REPOSITORY.git" "$head"
test "$(git -C "$RUNNER_TEMP/head" rev-parse FETCH_HEAD)" = "$head"
echo "fetched $REPOSITORY at $head"
: > "$RUNNER_TEMP/deps.args"
if git -C "$RUNNER_TEMP/head" cat-file -e "$head:.sv/required-checks.json" 2>/dev/null; then
  git -C "$RUNNER_TEMP/head" show "$head:.sv/required-checks.json" > "$RUNNER_TEMP/declaration.json"
  python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
for x in d.get("dependencies", []) if isinstance(d, dict) else []:
    print(x["id"], x["repository"], x["commit"])' "$RUNNER_TEMP/declaration.json" 2>/dev/null |
  while read -r id repo commit; do
    git init -q "$RUNNER_TEMP/dep-$id"
    git -C "$RUNNER_TEMP/dep-$id" fetch -q --no-tags --depth 1 "https://github.com/$repo.git" "$commit"
    echo "--dependency $id=$RUNNER_TEMP/dep-$id" >> "$RUNNER_TEMP/deps.args"
    echo "fetched dependency $id: $repo at $commit"
  done
else
  echo "head declares no .sv/required-checks.json"
fi
