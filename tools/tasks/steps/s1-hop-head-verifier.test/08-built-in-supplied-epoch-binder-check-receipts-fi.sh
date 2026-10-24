set -euo pipefail
python3 - "$RUNNER_TEMP/p1" <<'PY'
import sys, tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1] + "/resident-runtime"); sys.path.insert(0, "tests")
import sv_work_items as w
import test_s1_sv_check_receipts as t
for supplied, want in (("4000", "ALLOW"), ("4001", "DENY")):
    with tempfile.TemporaryDirectory() as tmp:
        _, receipts = t.Fixture(Path(tmp), {"README": b"x\n"}, supplied=supplied).mint()
    r = receipts["supplied-epoch-binder-check"]
    assert r["disposition"] == want, r
    w.validate_check_receipt(r)
    print(supplied, r["disposition"], r.get("failure_code"), "accepted by sv_work_items.validate_check_receipt")
PY
