python3 - <<'PY'
import json
for c in ("7898cedb", "978b8880"):
    d = "evidence/stage-evaluations/NWI-S0-StegVerse-Labs-" + c
    e = json.load(open(d + "/evaluation.json"))
    assert json.load(open("sandbox/s1-stage-evaluations/NWI-S0-StegVerse-Labs-" + c + ".json"))["manifest_source"] == "CONTRACT_PINS", c
    assert e["manifest_source"] == "CONTRACT_PINS", c
    assert e["evaluation_subject"]["manifest_blob"] == e["manifest"]["blob"] == "20b37917e1454ec788e8f1b8c75d1562ba76d1b3", c
    assert e["contract_pins"]["sha256"].startswith("sha256:317aef68"), c
print("both stage evaluations: manifest_source CONTRACT_PINS, manifest_blob", e["manifest"]["blob"], e["contract_pins"]["sha256"])
PY
