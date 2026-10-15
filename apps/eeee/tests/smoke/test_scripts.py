import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_restart_recovery_smoke_script_reports_interrupted_state():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke_restart_recovery.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["state"] == "interrupted"
    assert payload["recovered"] == [payload["requestId"]]
