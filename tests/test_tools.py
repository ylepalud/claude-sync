import os
import shutil

import pytest

from claude_sync import manifest, paths, tools
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Manifest, Tool
from claude_sync.tools import Conflict, Requirement, ToolStatus


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("rtk 0.20.0", (0, 20, 0)),
        ("gh version 2.101.0 (2026-09-15)", (2, 101, 0)),
        ("uv 0.11.7 (Homebrew 2026-09-01)", (0, 11, 7)),
        ("1.12.0", (1, 12, 0)),
        ("jq-1.6", (1, 6)),
        ("no number here, only 7", None),
        ("", None),
    ],
)
def test_parse_version(text, expected):
    assert tools.parse_version(text) == expected


def test_check_ok_reads_the_installed_version(fake_tools):
    fake_tools.install("fakejq", "rtk 0.20.0")
    assert tools.check(Tool("fakejq", "0.8")) == ToolStatus("fakejq", "ok", "0.20.0", "0.8")


def test_check_without_a_minimum_is_ok_even_with_an_unreadable_version(fake_tools):
    fake_tools.install("fakejq", "no version")
    assert tools.check(Tool("fakejq")) == ToolStatus("fakejq", "ok", None, None)


def test_check_missing_when_not_found(fake_tools):
    assert tools.check(Tool("fakejq", "1.0")) == ToolStatus("fakejq", "missing", None, "1.0")


def test_check_missing_on_non_zero_exit(fake_tools):
    fake_tools.install("fakejq", "jq-9.9", exit=1)
    assert tools.check(Tool("fakejq")).status == "missing"


def test_check_missing_on_timeout(fake_tools, monkeypatch):
    monkeypatch.setattr(tools, "CHECK_TIMEOUT", 0.3)
    fake_tools.install("fakejq", "jq-9.9", sleep=5)
    assert tools.check(Tool("fakejq")).status == "missing"


def test_check_has_a_ten_second_timeout():
    assert tools.CHECK_TIMEOUT == 10


def test_check_too_old(fake_tools):
    fake_tools.install("fakejq", "jq-1.6")
    assert tools.check(Tool("fakejq", "1.7")) == ToolStatus("fakejq", "too-old", "1.6", "1.7")


def test_check_pads_missing_components_with_zeros(fake_tools):
    fake_tools.install("fakejq", "jq-1.6")
    assert tools.check(Tool("fakejq", "1.6.0")).status == "ok"
    assert tools.check(Tool("fakejq", "1.6.1")).status == "too-old"


def test_check_compares_numbers_not_text(fake_tools):
    fake_tools.install("fakejq", "fakejq 0.20.0")
    assert tools.check(Tool("fakejq", "0.8")).status == "ok"


def test_check_unreadable_version_with_a_minimum_is_too_old(fake_tools):
    fake_tools.install("fakejq", "dev build")
    assert tools.check(Tool("fakejq", "1.0")) == ToolStatus("fakejq", "too-old", None, "1.0")


def test_check_runs_the_check_command_without_a_shell(fake_tools):
    fake_tools.install("fakejq", "jq-1.6")
    marker = paths.config_home().parent / "marker"
    tool = Tool("fakejq", None, f"fakejq --version ; touch {marker}")
    assert tools.check(tool).status == "ok"
    assert not marker.exists()


def test_check_with_a_missing_executable_under_a_custom_command(fake_tools):
    assert tools.check(Tool("fakejq", None, "fakejq -V")).status == "missing"


def test_check_gives_the_tool_a_closed_stdin(fake_tools):
    fake_tools.install("fakejq", "", read_stdin=True)
    read_end, write_end = os.pipe()
    os.write(write_end, b"9.9.9")
    os.close(write_end)
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        result = tools.check(Tool("fakejq"))
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(read_end)
    assert result == ToolStatus("fakejq", "ok", None, None)


def test_check_defaults_to_asking_for_the_version(fake_tools):
    fake_tools.install("fakejq", "jq-1.6", requires_arg="--version")
    assert tools.check(Tool("fakejq", "1.0")).status == "ok"


def test_check_unreadable_version_is_too_old_even_for_a_zero_minimum(fake_tools):
    fake_tools.install("fakejq", "dev build")
    assert tools.check(Tool("fakejq", "0.0")) == ToolStatus("fakejq", "too-old", None, "0.0")


def test_parse_version_reads_ascii_digits_only():
    assert tools.parse_version("\u0663.\u0664") is None


def m(*declared: Tool) -> Manifest:
    return Manifest((), (), None, tools=declared)


def test_merge_takes_the_highest_minimum_and_lists_requiring_profiles():
    requirements, conflicts = tools.merge(
        {
            "work": m(Tool("gh", "2.10", None, "brew:gh")),
            "perso": m(Tool("gh", "2.9", None, "brew:gh"), Tool("jq")),
        }
    )
    assert conflicts == []
    assert requirements == [
        Requirement(Tool("gh", "2.10", None, "brew:gh"), ("perso", "work")),
        Requirement(Tool("jq"), ("perso",)),
    ]


def test_merge_compares_minimums_numerically_and_ignores_missing_ones():
    requirements, _ = tools.merge(
        {"a": m(Tool("x", "1.9")), "b": m(Tool("x", "1.10")), "c": m(Tool("x"))}
    )
    assert requirements[0].tool.version == "1.10"
    only_none, _ = tools.merge({"a": m(Tool("x")), "b": m(Tool("x"))})
    assert only_none[0].tool.version is None


def test_merge_takes_check_and_recipe_each_from_the_first_profile_declaring_them():
    requirements, conflicts = tools.merge(
        {
            "zeta": m(Tool("x", None, "x -V", "brew:x")),
            "beta": m(Tool("x", None, None, "brew:x")),
            "alpha": m(Tool("x", "1.0", None, None)),
        }
    )
    assert conflicts == []
    assert requirements == [
        Requirement(Tool("x", "1.0", "x -V", "brew:x"), ("alpha", "beta", "zeta"))
    ]


def test_merge_takes_the_check_of_the_first_profile_when_two_declare_one():
    requirements, _ = tools.merge(
        {"b": m(Tool("x", None, "x --other")), "a": m(Tool("x", None, "x -V"))}
    )
    assert requirements[0].tool.check == "x -V"


def test_merge_reports_different_recipes_as_conflicts():
    requirements, conflicts = tools.merge(
        {
            "perso": m(Tool("gh", None, None, "brew:gh")),
            "work": m(Tool("gh", None, None, "script:install-gh")),
        }
    )
    assert requirements[0].tool.install == "brew:gh"
    assert conflicts == [Conflict("gh", (("perso", "brew:gh"), ("work", "script:install-gh")))]


def test_merge_of_nothing_is_empty():
    assert tools.merge({}) == ([], [])
    assert tools.merge({"a": m()}) == ([], [])


def test_fix_command_per_manager_uses_absolute_paths(fake_managers):
    assert tools.fix_command("npm:@scope/pkg") == [
        shutil.which("npm"), "install", "-g", "@scope/pkg@latest",
    ]  # fmt: skip
    assert tools.fix_command("uv:ruff") == [
        shutil.which("uv"), "tool", "install", "--upgrade", "ruff",
    ]  # fmt: skip
    assert tools.fix_command("cargo:ripgrep") == [
        shutil.which("cargo"), "install", "--force", "ripgrep",
    ]  # fmt: skip


def test_fix_command_runs_a_script_through_bin_sh():
    assert tools.fix_command("script:echo a; echo b") == ["/bin/sh", "-c", "echo a; echo b"]


def test_fix_command_brew_installs_what_is_not_listed(fake_managers):
    brew = shutil.which("brew")
    assert tools.fix_command("brew:jq") == [brew, "install", "jq"]
    assert fake_managers.calls() == [["brew", "list", "jq"]]


def test_fix_command_brew_upgrades_what_is_listed(fake_managers):
    fake_managers.listed("jq")
    assert tools.fix_command("brew:jq") == [shutil.which("brew"), "upgrade", "jq"]


def test_fix_command_refuses_a_manager_that_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ClaudeSyncError, match="npm.*not found on PATH"):
        tools.fix_command("npm:x")


def test_fix_command_never_runs_a_real_brew(isolated_environment):
    # The blocking brew exits 2: not "not listed", so no install is guessed.
    with pytest.raises(ClaudeSyncError, match="brew list"):
        tools.fix_command("brew:jq")


def test_resolved_path_is_the_first_binary_on_path(fake_tools, tmp_path, monkeypatch):
    assert tools.resolved_path("fakejq") is None
    later = tmp_path / "later"
    later.mkdir()
    (later / "fakejq").write_text("#!/bin/sh\n")
    (later / "fakejq").chmod(0o755)
    monkeypatch.setenv("PATH", f"{later}{os.pathsep}{os.environ['PATH']}")
    fake_tools.install("fakejq", "jq-1.6")
    # `later` was put on PATH last and so first: it shadows the stub.
    assert tools.resolved_path("fakejq") == str(later / "fakejq")
    monkeypatch.setenv("PATH", f"{fake_tools.bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert tools.resolved_path("fakejq") == fake_tools.path("fakejq")


def test_all_profiles_lists_directories_with_a_manifest_in_name_order(isolated_environment):
    assert tools.all_profiles() == []
    for name in ("work", "perso"):
        directory = paths.profile_dir(name)
        directory.mkdir(parents=True)
        (directory / manifest.MANIFEST_FILE).write_text("")
    (paths.profile_dir("empty")).mkdir()
    (paths.profiles_root() / "stray-file").write_text("")
    (paths.profile_dir("Bad Name")).mkdir()
    (paths.profile_dir("Bad Name") / manifest.MANIFEST_FILE).write_text("")
    assert tools.all_profiles() == ["perso", "work"]


def fake_brew(tmp_path, monkeypatch, script):
    bin_dir = tmp_path / "brew-bin"
    bin_dir.mkdir()
    (bin_dir / "brew").write_text(f"#!/bin/sh\n{script}\n")
    (bin_dir / "brew").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_brew_list_times_out_with_a_clear_error(tmp_path, monkeypatch):
    fake_brew(tmp_path, monkeypatch, "sleep 5")
    monkeypatch.setattr(tools, "BREW_LIST_TIMEOUT", 0.3)
    with pytest.raises(ClaudeSyncError, match="brew list jq timed out"):
        tools.fix_command("brew:jq")


def test_brew_list_has_a_closed_stdin(tmp_path, monkeypatch):
    fake_brew(tmp_path, monkeypatch, '[ -z "$(cat)" ] && exit 1; exit 0')
    read_end, write_end = os.pipe()
    os.write(write_end, b"data")
    os.close(write_end)
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        command = tools.fix_command("brew:jq")
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(read_end)
    assert command[1] == "install"
