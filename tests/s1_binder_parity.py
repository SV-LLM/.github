"""supplied-epoch-binder-check parity with P1's in-repo reference sv_work_items.verify_admission_hb_epoch (argv[1] = a P1 tree at the pin)."""
import sys, json
sys.path.insert(0, sys.argv[1] + "/resident-runtime"); sys.path.insert(0, "tests"); sys.path.insert(0, "sandbox")
import sv_work_items as w
import test_s1_sv_check_receipts as t
import s1_supplied_epoch_binder as eb
H = t.LEDGER_HEAD
rbs = {"ok": t.sealed_readback(), "null": t.sealed_readback(None, hb_epoch_source=...),
       "clock": t.sealed_readback(hb_epoch_source={"ledger_head": H, "field": eb.HB_EPOCH_SOURCE_FIELD, "derived_from_clock": True}),
       "float": t.sealed_readback("4000.0"), "31": t.sealed_readback("31"), "other": t.sealed_readback(ledger_head="b" * 40),
       "notallow": t.sealed_readback(disposition="FAIL_CLOSED"), "broken": {**t.sealed_readback(), "hb_epoch": "4001"},
       "real": json.load(open("sandbox/s1-base-state-readbacks/StegVerse-Labs-bfcf031811caaa65bc44a48c894fce19800b5d90.json")),
       "none": None}
n = 0
for rn, rb in rbs.items():
    head = "a5bb54d81893b392a3ce28182986fc39857807e1" if rn == "real" else H
    for s in ("4000", "4001", "04000", "+4000", None, "UNKNOWN_NOT_AUTHENTICALLY_OBSERVED"):
        mine = eb.binder_check(s, rb, head)
        try:
            w.verify_admission_hb_epoch(s, rb, head); theirs = ("ALLOW", None)
        except Exception as e:
            rec = getattr(e, "record", {}); theirs = (rec.get("disposition"), rec.get("failure_code"))
        assert (mine["disposition"], mine.get("failure_code")) == theirs, (rn, s, mine["disposition"], mine.get("failure_code"), theirs)
        n += 1
print(n, "cases: binder_check agrees with P1 sv_work_items.verify_admission_hb_epoch")
