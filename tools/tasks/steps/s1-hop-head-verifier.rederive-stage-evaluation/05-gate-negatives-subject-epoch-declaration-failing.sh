set -euo pipefail
git config --global user.name ci && git config --global user.email ci@invalid
python3 -B tests/s1_gate_negatives.py "$RUNNER_TEMP/labs"
