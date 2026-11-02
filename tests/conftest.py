import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Read before any fixture clears it; the e2e module reads its own copy the same way.
# It lifts the real-claude guard for the e2e module only.
E2E = os.environ.get("CLAUDE_SYNC_E2E") == "1"
FAKE_CLAUDE = Path(__file__).with_name("fake_claude.py")


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Keep every test away from the real home, git config and Keychain."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in (
        "XDG_CONFIG_HOME",
        "CLAUDE_CONFIG_DIR",
        "DENYLIST",
        "CLAUDE_SYNC_PROFILE",
        "CLAUDE_SYNC_OVERRIDE",
        "CLAUDE_SYNC_PROMPT",
        "CLAUDE_SYNC_USER_CONFIG_DIR",
        "CLAUDE_SYNC_E2E",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    return home


def _install_command(bin_dir: Path, script: str, monkeypatch) -> None:
    command = bin_dir / "claude"
    command.write_text(script)
    command.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture(autouse=True)
def block_real_claude(request, tmp_path_factory, monkeypatch):
    """Put a `claude` that refuses to run first on PATH, except in the e2e module."""
    if E2E and request.module.__name__.endswith("test_e2e"):
        return
    script = '#!/bin/sh\necho "real claude blocked in tests" >&2\nexit 1\n'
    _install_command(tmp_path_factory.mktemp("blocked-bin"), script, monkeypatch)


@dataclass
class FakeClaude:
    root: Path

    def seed(self, profile_dir: Path, state: dict) -> None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "fake-claude.json").write_text(json.dumps(state))

    def state(self, profile_dir: Path) -> dict:
        return json.loads((profile_dir / "fake-claude.json").read_text())

    def log(self, profile_dir: Path) -> list[dict]:
        file = profile_dir / "fake-claude.log"
        if not file.exists():
            return []
        return [json.loads(line) for line in file.read_text().splitlines()]

    def calls(self, profile_dir: Path) -> list[list[str]]:
        return [entry["argv"] for entry in self.log(profile_dir)]

    def make_upstream(
        self, name: str, plugins: dict[str, str], branches=("main",)
    ) -> tuple[Path, str]:
        """A local git repository serving marketplace `name`; HEAD of the first branch."""
        repo = self.root / "upstreams" / name
        (repo / ".claude-plugin").mkdir(parents=True)
        catalog = {"name": name, "plugins": [{"name": p, "version": v} for p, v in plugins.items()]}
        (repo / ".claude-plugin" / "marketplace.json").write_text(json.dumps(catalog))

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
            ).stdout.strip()

        git("init", "--quiet", "--initial-branch", branches[0])
        git("add", ".")
        git(
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "catalog",
        )
        for branch in branches[1:]:
            git("branch", branch)
        return repo, git("rev-parse", "HEAD")


@pytest.fixture
def fake_claude(block_real_claude, tmp_path_factory, monkeypatch):
    """Install tests/fake_claude.py as `claude`, ahead of the blocking one."""
    script = f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n'
    _install_command(tmp_path_factory.mktemp("fake-bin"), script, monkeypatch)
    return FakeClaude(tmp_path_factory.mktemp("fake-claude"))


def _is_case_sensitive(directory) -> bool:
    probe = directory / "CaseProbe"
    probe.mkdir()
    try:
        return not (directory / "caseprobe").exists()
    finally:
        probe.rmdir()


@pytest.fixture
def case_insensitive_fs(tmp_path):
    if _is_case_sensitive(tmp_path):
        pytest.skip("the file system of tmp_path is case-sensitive")


@pytest.fixture
def case_sensitive_fs(tmp_path):
    if not _is_case_sensitive(tmp_path):
        pytest.skip("the file system of tmp_path is case-insensitive")
