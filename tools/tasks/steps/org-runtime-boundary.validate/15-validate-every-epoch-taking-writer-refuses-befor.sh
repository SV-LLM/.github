set -euo pipefail
# The two manifest-ingress CLI cases import the StegVerse SDK; without it they were skipped here. Read the
# public SDK anonymously at the same pin as organization-manifest-ingress-validation (no credential), so this
# group runs them with 0 skipped tests.
sdk="$RUNNER_TEMP/stegverse-sdk"
git init -q "$sdk"
GIT_TERMINAL_PROMPT=0 git -C "$sdk" -c credential.helper= fetch -q --depth 1 https://github.com/StegVerse-org/StegVerse-SDK 74d9b473aa415b06a9d550c28b2779a691b4ba32
git -C "$sdk" checkout -q --detach FETCH_HEAD
test "$(git -C "$sdk" rev-parse HEAD)" = 74d9b473aa415b06a9d550c28b2779a691b4ba32
STEGVERSE_SDK_ROOT="$sdk" STEGVERSE_SDK_REQUIRED=1 python -B -m unittest discover -s org-runtime/tests -p 'test_writer_epoch_refusal_order.py' -v
