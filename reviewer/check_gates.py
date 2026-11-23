"""Fail the job unless every automatic gate of the render mode passed."""
import json
import sys
from pathlib import Path

batch = Path(sys.argv[1]).resolve()
gates = [
    ("runtime witness", "runtime-witness.json", lambda d: d.get("status") == "success" and d.get("exit_code") == 0),
    ("runtime witness index", "runtime-witness-index.json", lambda d: d.get("pass") is True and not d.get("failures")),
    ("runtime witness audit", "native-runtime-audit.json", lambda d: d.get("status") == "PASS" or d.get("pass") is True),
    ("reviewer independent media audit", "reviewer-independent-media.json", lambda d: d.get("status") == "PASS"),
    ("static scale audit", "scale-static.json", lambda d: d.get("decision") == "PASS"),
    ("finite-strain controls", "finite-strain-controls.json", lambda d: d.get("controlsDecision") == "PASS"),
    ("model domain checks", "model-domain.json", lambda d: d.get("decision") == "PASS"),
    ("exact-head tests", "exact-head-tests.json", lambda d: d.get("status") == "PASS"),
]
failed = []
summary = {}
for label, name, check in gates:
    path = batch / name
    if not path.is_file():
        failed.append(label + ": missing " + name)
        continue
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        failed.append(label + ": unreadable (" + str(exc) + ")")
        continue
    ok = check(data)
    summary[label] = "PASS" if ok else "FAIL"
    if not ok:
        failed.append(label + ": gate did not pass")
for entry in sorted(batch.glob("*/audit_media.json")):
    data = json.loads(entry.read_text())
    if data.get("status") != "PASS":
        failed.append("case media audit failed: " + entry.parent.name)
for entry in sorted(batch.glob("*/audit_physics.json")):
    data = json.loads(entry.read_text())
    if data.get("status") != "PASS":
        failed.append("case physics audit failed: " + entry.parent.name)
print(json.dumps({"gates": summary, "failures": failed}, indent=2))
raise SystemExit(0 if not failed else 1)
