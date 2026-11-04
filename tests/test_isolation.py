import os
import shutil
import subprocess
import sys
from pathlib import Path

# Read at import, before the fixtures change them.
ORIGINAL_PATH = os.environ["PATH"]


def test_home_is_a_temporary_directory(tmp_path):
    assert Path(os.environ["HOME"]).is_relative_to(tmp_path)


def test_config_locations_are_unset():
    for name in ("XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "DENYLIST"):
        assert name not in os.environ


def test_shell_integration_variables_are_unset():
    for name in (
        "CLAUDE_SYNC_PROFILE",
        "CLAUDE_SYNC_OVERRIDE",
        "CLAUDE_SYNC_PROMPT",
        "CLAUDE_SYNC_USER_CONFIG_DIR",
    ):
        assert name not in os.environ


def test_git_global_and_system_config_are_disabled():
    assert os.environ["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert os.environ["GIT_CONFIG_SYSTEM"] == "/dev/null"


def test_real_claude_is_blocked():
    result = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    assert result.returncode == 1
    assert "real claude blocked in tests" in result.stderr


def test_e2e_switch_is_cleared():
    assert "CLAUDE_SYNC_E2E" not in os.environ


def test_fake_claude_replaces_the_guard(fake_claude, tmp_path):
    profile = tmp_path / "profile"
    fake_claude.seed(profile, {})
    result = subprocess.run(
        ["claude", "plugin", "list", "--json"],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_CONFIG_DIR": str(profile)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
    assert fake_claude.calls(profile) == [["plugin", "list", "--json"]]


def test_e2e_switch_keeps_the_guard_outside_the_e2e_module(tmp_path):
    """With CLAUDE_SYNC_E2E=1, a non-e2e test still gets the blocking claude."""
    stand_in = tmp_path / "real-bin"
    stand_in.mkdir()
    (stand_in / "claude").write_text("#!/bin/sh\necho real claude ran\n")
    (stand_in / "claude").chmod(0o755)
    env = {
        **os.environ,
        "CLAUDE_SYNC_E2E": "1",
        "PATH": f"{stand_in}{os.pathsep}{ORIGINAL_PATH}",
    }
    test = f"{Path(__file__)}::test_real_claude_is_blocked"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout


def test_real_pgrep_and_launchctl_are_blocked():
    for program in ("pgrep", "launchctl"):
        result = subprocess.run([program, "-x", "claude"], capture_output=True, text=True)
        assert result.returncode == 2, program
        assert f"real {program} blocked in tests" in result.stderr


def test_fake_system_replaces_the_guard(fake_system, monkeypatch):
    monkeypatch.setenv("FAKE_PGREP_PIDS", "12 34")
    pgrep = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True)
    assert (pgrep.returncode, pgrep.stdout) == (0, "12\n34\n")
    monkeypatch.setenv("FAKE_PGREP_PIDS", "")
    assert subprocess.run(["pgrep", "-x", "claude"], capture_output=True).returncode == 1
    launchctl = subprocess.run(["launchctl", "unsetenv", "X"], capture_output=True)
    assert launchctl.returncode == 0
    monkeypatch.setenv("FAKE_LAUNCHCTL_EXIT", "5")
    assert subprocess.run(["launchctl", "list"], capture_output=True).returncode == 5
    assert fake_system.calls() == [
        ["pgrep", "-x", "claude"],
        ["pgrep", "-x", "claude"],
        ["launchctl", "unsetenv", "X"],
        ["launchctl", "list"],
    ]
    assert fake_system.log_file == Path(os.environ["HOME"]) / ".fake-system.log"


def test_real_security_is_blocked():
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "x", "-w"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "real security blocked in tests" in result.stderr


def test_fake_keychain_replaces_the_guard(fake_keychain):
    fake_keychain.set("svc", "one")
    fake_keychain.set("svc", "two", account="acct")
    run = lambda *args: subprocess.run(  # noqa: E731
        ["security", "find-generic-password", *args, "-w"], capture_output=True, text=True
    )
    assert (run("-s", "svc").returncode, run("-s", "svc").stdout) == (0, "one\n")
    assert run("-s", "svc", "-a", "acct").stdout == "two\n"
    missing = run("-s", "nope")
    assert missing.returncode == 44
    assert "could not be found in the keychain" in missing.stderr
    assert fake_keychain.calls()[0] == ["find-generic-password", "-s", "svc", "-w"]


def test_real_package_managers_are_blocked():
    for program in ("brew", "npm", "uv", "cargo"):
        result = subprocess.run([program, "--version"], capture_output=True, text=True)
        assert result.returncode == 2, program
        assert f"real {program} blocked in tests" in result.stderr


def run(*argv):
    return subprocess.run(list(argv), capture_output=True, text=True)


def test_fake_tool_prints_its_configured_output_and_is_absent_otherwise(fake_tools):
    assert shutil.which("fakejq") is None
    fake_tools.install("fakejq", "jq-1.6")
    result = run("fakejq", "--version")
    assert (result.returncode, result.stdout) == (0, "jq-1.6\n")
    fake_tools.install("faketool", "faketool 2.0.1", exit=3)
    assert run("faketool").returncode == 3
    assert fake_tools.path("faketool") == shutil.which("faketool")
    fake_tools.remove("fakejq")
    assert shutil.which("fakejq") is None


def test_fake_tool_exits_127_when_its_entry_is_gone(fake_tools):
    fake_tools.install("fakejq", "jq-1.6")
    fake_tools.forget("fakejq")
    result = run("fakejq", "--version")
    assert result.returncode == 127
    assert "not found" in result.stderr


def test_fake_managers_replace_the_guard_and_install_tools(fake_managers, fake_tools):
    fake_managers.provides("brew", "jq", tool="fakejq", output="jq-1.7.1")
    assert run("brew", "list", "jq").returncode == 1
    assert shutil.which("fakejq") is None
    result = run("brew", "install", "jq")
    assert result.returncode == 0, result.stderr
    assert run("fakejq", "--version").stdout == "jq-1.7.1\n"
    assert run("brew", "list", "jq").returncode == 0
    assert fake_managers.calls() == [
        ["brew", "list", "jq"],
        ["brew", "install", "jq"],
        ["brew", "list", "jq"],
    ]


def test_fake_managers_cover_npm_uv_and_cargo(fake_managers, fake_tools):
    fake_managers.provides("npm", "@scope/pkg", tool="faketool", output="faketool 1.0.0")
    fake_managers.provides("uv", "uvpkg", tool="fakeuv", output="fakeuv 2.0")
    fake_managers.provides("cargo", "crate", tool="fakecargo", output="fakecargo 3.0")
    assert run("npm", "install", "-g", "@scope/pkg@latest").returncode == 0
    assert run("uv", "tool", "install", "--upgrade", "uvpkg").returncode == 0
    assert run("cargo", "install", "--force", "crate").returncode == 0
    assert run("faketool").stdout == "faketool 1.0.0\n"
    assert run("fakeuv").stdout == "fakeuv 2.0\n"
    assert run("fakecargo").stdout == "fakecargo 3.0\n"


def test_fake_managers_fail_on_unknown_packages_and_forced_failures(fake_managers):
    unknown = run("cargo", "install", "--force", "nothing")
    assert unknown.returncode == 1 and "no such package" in unknown.stderr
    fake_managers.provides("brew", "jq", tool="fakejq", output="jq-1")
    fake_managers.fail("brew", "jq")
    broken = run("brew", "install", "jq")
    assert broken.returncode == 1 and "forced failure" in broken.stderr
    assert shutil.which("fakejq") is None
