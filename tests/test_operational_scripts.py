import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script_name",
    [
        "create_event_coverage_template.py",
        "import_corporate_events.py",
        "kite_read_only_smoke.py",
        "refresh_nifty500.py",
    ],
)
def test_operational_script_help_runs_without_external_services(script_name: str) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts" / script_name
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
