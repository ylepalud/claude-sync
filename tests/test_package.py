import subprocess
import sys

import claude_sync


def test_version_is_the_packaged_version():
    assert claude_sync.__version__ == "0.1.0"


def test_python_dash_m_runs_the_cli():
    result = subprocess.run(
        [sys.executable, "-m", "claude_sync", "--version"], capture_output=True, text=True
    )
    assert result.stdout == "claude-sync 0.1.0\n"
    assert result.returncode == 0
