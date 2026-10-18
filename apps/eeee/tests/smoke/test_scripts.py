import json
import os
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


def test_ollama_smoke_script_runs_from_file_path_and_reports_missing_model():
    environment = os.environ.copy()
    environment.pop("EEEE_OLLAMA_MODEL", None)
    environment.pop("OLLAMA_MODEL", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke_ollama.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "model_missing"
