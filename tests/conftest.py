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
FAKE_SYSTEM = {
    "pgrep": Path(__file__).with_name("fake_pgrep.py"),
    "launchctl": Path(__file__).with_name("fake_launchctl.py"),
}


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
        "FAKE_CLAUDE_WRITES_STATE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    return home


def _install_command(bin_dir: Path, script: str, monkeypatch, name: str = "claude") -> None:
    command = bin_dir / name
    command.write_text(script)
    command.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture(autouse=True)
def block_real_system(tmp_path_factory, monkeypatch):
    """Put a `pgrep` and a `launchctl` that refuse to run first on PATH, in every test.

    They exit 2, not 1: `pgrep` exits 1 for "no process", which must not be faked.
    """
    bin_dir = tmp_path_factory.mktemp("blocked-system-bin")
    for name in FAKE_SYSTEM:
        script = f'#!/bin/sh\necho "real {name} blocked in tests" >&2\nexit 2\n'
        _install_command(bin_dir, script, monkeypatch, name)


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


@dataclass
class FakeSystem:
    log_file: Path

    def calls(self) -> list[list[str]]:
        """Every `pgrep` and `launchctl` call, in order, program name first."""
        if not self.log_file.exists():
            return []
        return [json.loads(line)["argv"] for line in self.log_file.read_text().splitlines()]


@pytest.fixture
def fake_system(block_real_system, isolated_environment, tmp_path_factory, monkeypatch):
    """Install tests/fake_pgrep.py and tests/fake_launchctl.py ahead of the blocking ones."""
    bin_dir = tmp_path_factory.mktemp("fake-system-bin")
    for name, stub in FAKE_SYSTEM.items():
        script = f'#!/bin/sh\nexec "{sys.executable}" "{stub}" "$@"\n'
        _install_command(bin_dir, script, monkeypatch, name)
    for name in ("FAKE_PGREP_PIDS", "FAKE_PGREP_PIDS_claude", "FAKE_PGREP_PIDS_Claude"):
        monkeypatch.delenv(name, raising=False)
    for name in ("FAKE_LAUNCHCTL_EXIT",):
        monkeypatch.delenv(name, raising=False)
    return FakeSystem(isolated_environment / ".fake-system.log")


LEGACY_GITIGNORE = """\
/*
!/.gitignore
!/settings.json
!/skills/
!/rules/
!/plugins/
/plugins/*
!/plugins/installed_plugins.json
!/plugins/known_marketplaces.json
"""


@dataclass
class LegacyClaude:
    home: Path
    root: Path
    """`~/.claude`, also the fake claude's config dir."""
    commit: str
    """HEAD of the `tools` marketplace upstream and of its copy in the profile."""
    fake_claude: FakeClaude


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def legacy_claude(isolated_environment, fake_claude):
    """A realistic `~/.claude` and `~/.claude.json` in the isolated HOME.

    A git repository with an allowlist `.gitignore` and one commit; an absolute
    hook path in `settings.json`; a skill linked outside (`skills/out`) and one
    inside (`skills/in`); a rule naming `~/.claude/hooks`; a session under
    `projects/`; one user-scope plugin `helper@tools` from a GitHub marketplace,
    known to the fake claude and listed in the plugin lists.
    """
    home = isolated_environment
    root = home / ".claude"
    upstream, commit = fake_claude.make_upstream("tools", {"helper": "1.0.0"})
    market = root / "plugins" / "marketplaces" / "tools"
    market.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "--quiet", str(upstream), str(market)], check=True)
    cache = root / "plugins" / "cache" / "tools" / "helper" / "1.0.0"
    cache.mkdir(parents=True)
    (cache / "plugin.json").write_text('{"name": "helper"}\n')
    (root / "plugins" / "data").mkdir()
    (root / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "helper@tools": [
                        {"scope": "user", "installPath": str(cache), "version": "1.0.0"}
                    ]
                },
            },
            indent=2,
        )
    )
    (root / "plugins" / "known_marketplaces.json").write_text(
        json.dumps(
            {
                "tools": {
                    "source": {"source": "github", "repo": "perso/tools"},
                    "installLocation": str(market),
                }
            },
            indent=2,
        )
    )
    fake_claude.seed(
        root,
        {
            "marketplaces": [
                {
                    "name": "tools",
                    "source": "github",
                    "repo": "perso/tools",
                    "installLocation": str(market),
                }
            ],
            "plugins": [
                {"id": "helper@tools", "version": "1.0.0", "scope": "user", "enabled": True}
            ],
            "catalog": {"tools": {"helper": "1.0.0"}},
            "upstream": {"perso/tools": str(upstream)},
        },
    )
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": f"{home}/.claude/hooks/x.sh"}],
                }
            ]
        },
        "env": {"STATE_FILE": f"{home}/.claude.json"},
    }
    (root / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (root / "hooks").mkdir()
    (root / "hooks" / "x.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "hooks" / "x.sh").chmod(0o755)
    outside = home / ".agents" / "skills" / "out"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_text("# out\n")
    (root / "skills").mkdir()
    (root / "skills" / "out").symlink_to("../../.agents/skills/out")
    (root / "skills" / "in").symlink_to("../rules")
    (root / "rules").mkdir()
    (root / "rules" / "r.md").write_text("Hooks live in ~/.claude/hooks.\n")
    (root / "projects" / "p").mkdir(parents=True)
    (root / "projects" / "p" / "s.jsonl").write_text('{"type": "user"}\n')
    (root / ".gitignore").write_text(LEGACY_GITIGNORE)
    (home / ".claude.json").write_text('{"numStartups": 3}\n')
    _git(root, "init", "--quiet", "--initial-branch", "main")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "config",
    )
    return LegacyClaude(home, root, commit, fake_claude)


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
