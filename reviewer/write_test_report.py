"""Record the exact-head test-suite result as a reviewable artifact."""
import json
import os
import sys
from pathlib import Path

batch = Path(sys.argv[1]).resolve()
code = int(sys.argv[2])
stdout = (batch / "pytest-stdout.txt").read_text()
report = {
    "schema": "exact-head-tests-v1",
    "source_commit": os.environ["HEAD"],
    "pytest_exit_code": code,
    "pytest_stdout": stdout,
    "status": "PASS" if code == 0 else "FAIL",
}
(batch / "exact-head-tests.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": report["status"], "exit_code": code}))
