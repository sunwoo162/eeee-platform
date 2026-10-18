from pathlib import Path
import shutil
import subprocess


def test_repository_hygiene_allows_local_ignored_env_without_allowing_tracked_secrets():
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "check-repository.ps1"

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repository hygiene check passed." in result.stdout


def test_repository_hygiene_runs_under_windows_powershell_when_available():
    powershell = shutil.which("powershell")
    if powershell is None:
        return

    root = Path(__file__).resolve().parents[3]
    script = root / "scripts" / "check-repository.ps1"
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Repository hygiene check passed." in result.stdout
