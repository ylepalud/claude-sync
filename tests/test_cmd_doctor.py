import io
import json
import os
import shlex
import shutil

from claude_sync import manifest, paths
from claude_sync.cli import main
from claude_sync.manifest import Tool


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def declare(profile, *tools):
    """Write the manifest of `profile` with these tool tables."""
    directory = paths.profile_dir(profile)
    directory.mkdir(parents=True, exist_ok=True)
    manifest.save(directory / manifest.MANIFEST_FILE, manifest.Manifest((), (), None, tools=tools))


def tty(monkeypatch, answer="y"):
    stdin = io.StringIO()
    stdin.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", stdin)
    asked = []

    def fake_input(prompt=""):
        asked.append(prompt)
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    return asked


def no_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def test_a_present_tool_is_listed_ok_and_exits_0(capsys, fake_tools):
    path = fake_tools.install("fakertk", "fakertk 0.20.0")
    declare("work", Tool("fakertk", version="0.8"))
    code, out, _ = run(capsys, "doctor")
    assert code == 0
    line = next(line for line in out.splitlines() if "fakertk" in line)
    assert line.startswith("ok ")
    assert "installed 0.20.0" in line
    assert "required 0.8" in line
    assert "by work" in line
    assert f"path {path}" in line


def test_a_missing_tool_is_listed_with_its_profile_and_exits_4(capsys, fake_tools):
    declare("work", Tool("fakejq"))
    code, out, _ = run(capsys, "doctor")
    assert code == 4
    line = next(line for line in out.splitlines() if "fakejq" in line)
    assert line.startswith("missing ")
    assert "by work" in line
    assert "path -" in line


def test_a_too_old_tool_exits_4(capsys, fake_tools):
    fake_tools.install("fakejq", "fakejq-1.6")
    declare("work", Tool("fakejq", version="1.7"))
    code, out, _ = run(capsys, "doctor")
    assert code == 4
    line = next(line for line in out.splitlines() if "fakejq" in line)
    assert line.startswith("too-old ")
    assert "installed 1.6" in line
    assert "required 1.7" in line


def test_no_declared_tool_exits_0(capsys):
    code, out, _ = run(capsys, "doctor")
    assert code == 0
    assert "no tools declared" in out


def test_requirements_are_merged_across_profiles(capsys, fake_tools):
    fake_tools.install("fakejq", "fakejq-1.6")
    declare("perso", Tool("fakejq", version="1.5", install="brew:fakejq"))
    declare("work", Tool("fakejq", version="1.7"))
    code, out, _ = run(capsys, "doctor")
    assert code == 4
    lines = [line for line in out.splitlines() if "fakejq" in line]
    assert len(lines) == 1
    assert "required 1.7" in lines[0]
    assert "by perso, work" in lines[0]
    assert "recipe brew:fakejq" in lines[0]


def test_conflicting_recipes_are_reported_and_exit_4(capsys, fake_tools):
    fake_tools.install("fakegh", "fakegh version 2.0.0")
    declare("perso", Tool("fakegh", install="brew:fakegh"))
    declare("work", Tool("fakegh", install="script:install-gh"))
    code, out, _ = run(capsys, "doctor")
    assert code == 4
    line = next(line for line in out.splitlines() if line.startswith("conflict"))
    assert "fakegh" in line
    assert "perso brew:fakegh" in line
    assert "work script:install-gh" in line


def test_an_invalid_manifest_stops_doctor_with_exit_1(capsys):
    directory = paths.profile_dir("work")
    directory.mkdir(parents=True)
    (directory / manifest.MANIFEST_FILE).write_text('[[tool]]\nname = "x"\ninstall = "apt:x"\n')
    code, _, err = run(capsys, "doctor")
    assert code == 1
    assert "apt" in err


def test_json_lists_tools_conflicts_and_ok(capsys, fake_tools):
    path = fake_tools.install("fakertk", "fakertk 0.20.0")
    declare("work", Tool("fakertk", version="0.8", install="brew:fakertk"), Tool("fakejq"))
    code, out, _ = run(capsys, "doctor", "--json")
    assert code == 4
    assert json.loads(out) == {
        "tools": [
            {
                "name": "fakejq",
                "status": "missing",
                "installed": None,
                "required": None,
                "profiles": ["work"],
                "recipe": None,
                "path": None,
            },
            {
                "name": "fakertk",
                "status": "ok",
                "installed": "0.20.0",
                "required": "0.8",
                "profiles": ["work"],
                "recipe": "brew:fakertk",
                "path": str(path),
            },
        ],
        "conflicts": [],
        "ok": False,
    }


def test_json_reports_conflicts_with_their_recipes(capsys, fake_tools):
    fake_tools.install("fakegh", "fakegh 2.0.0")
    declare("perso", Tool("fakegh", install="brew:fakegh"))
    declare("work", Tool("fakegh", install="script:install-gh"))
    _, out, _ = run(capsys, "doctor", "--json")
    assert json.loads(out)["conflicts"] == [
        {
            "name": "fakegh",
            "recipes": [
                {"profile": "perso", "recipe": "brew:fakegh"},
                {"profile": "work", "recipe": "script:install-gh"},
            ],
        }
    ]


def test_json_ok_is_true_when_all_tools_are_ok(capsys, fake_tools):
    fake_tools.install("fakertk", "fakertk 0.20.0")
    declare("work", Tool("fakertk"))
    code, out, _ = run(capsys, "doctor", "--json")
    assert code == 0
    assert json.loads(out)["ok"] is True


def test_doctor_is_registered_after_adopt():
    from claude_sync import registry

    assert registry.COMMANDS[-1].name == "doctor"


def test_fix_json_without_yes_is_a_usage_error(capsys, fake_tools):
    declare("work", Tool("fakejq", install="brew:fakejq"))
    code, _, err = run(capsys, "doctor", "--fix", "--json")
    assert code == 2
    assert "--yes" in err


def brew_path():
    return shutil.which("brew")


SCRIPT = 'touch "$HOME/script-ran"'
SCRIPT_SHOWN = shlex.join(["/bin/sh", "-c", SCRIPT])


def test_fix_installs_a_missing_tool_and_reports_it_ok(capsys, fake_tools, fake_managers):
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", install="brew:fakejq"))
    code, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert code == 0
    assert fake_managers.calls() == [
        ["brew", "list", "fakejq"],
        ["brew", "install", "fakejq"],
    ]
    assert f"{brew_path()} install fakejq" in out
    assert out.splitlines()[-1].startswith("ok ")
    assert "fakejq" in out.splitlines()[-1]


def test_fix_without_a_tty_and_without_yes_exits_3_and_runs_nothing(
    capsys, monkeypatch, fake_tools, fake_managers
):
    no_tty(monkeypatch)
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", install="brew:fakejq"))
    code, _, err = run(capsys, "doctor", "--fix")
    assert code == 3
    assert f"{brew_path()} install fakejq" in err
    assert ["brew", "install", "fakejq"] not in fake_managers.calls()


def test_fix_asks_one_confirmation_listing_every_command(
    capsys, monkeypatch, fake_tools, fake_managers
):
    asked = tty(monkeypatch, "y")
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    fake_managers.provides("npm", "faketool", tool="faketool", output="faketool 2.0.0")
    declare(
        "work",
        Tool("fakejq", install="brew:fakejq"),
        Tool("faketool", install="npm:faketool"),
    )
    code, _, _ = run(capsys, "doctor", "--fix")
    assert code == 0
    assert len(asked) == 1
    assert f"{brew_path()} install fakejq" in asked[0]
    assert f"{shutil.which('npm')} install -g faketool@latest" in asked[0]


def test_declining_the_fix_runs_nothing(capsys, monkeypatch, fake_tools, fake_managers):
    tty(monkeypatch, "n")
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", install="brew:fakejq"))
    code, _, err = run(capsys, "doctor", "--fix")
    assert code == 0
    assert "cancelled" in err
    assert ["brew", "install", "fakejq"] not in fake_managers.calls()


def test_fix_upgrades_a_too_old_tool(capsys, fake_tools, fake_managers):
    fake_tools.install("fakejq", "fakejq-1.6")
    fake_managers.listed("fakejq")
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", version="1.7", install="brew:fakejq"))
    code, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert code == 0
    assert ["brew", "upgrade", "fakejq"] in fake_managers.calls()
    assert f"{brew_path()} upgrade fakejq" in out


def test_a_tool_still_too_old_names_the_binary_found_first(capsys, fake_tools, fake_managers):
    path = fake_tools.install("fakejq", "fakejq-1.6")
    fake_managers.listed("fakejq")
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.6")
    declare("work", Tool("fakejq", version="1.7", install="brew:fakejq"))
    code, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert code == 4
    assert f"still too-old: fakejq 1.6, found first at {path}" in out


def test_a_tool_without_a_recipe_is_reported_and_asks_nothing(
    capsys, monkeypatch, fake_tools, fake_managers
):
    no_tty(monkeypatch)
    declare("work", Tool("fakejq"))
    code, out, _ = run(capsys, "doctor", "--fix")
    assert code == 4
    assert fake_managers.calls() == []
    assert "still missing: fakejq" in out


def test_fix_with_everything_ok_asks_nothing(capsys, monkeypatch, fake_tools):
    no_tty(monkeypatch)
    fake_tools.install("fakertk", "fakertk 0.20.0")
    declare("work", Tool("fakertk", install="brew:fakertk"))
    code, _, _ = run(capsys, "doctor", "--fix")
    assert code == 0


def test_a_script_does_not_run_with_yes_and_no_tty(
    capsys, monkeypatch, fake_tools, isolated_environment
):
    no_tty(monkeypatch)
    declare("work", Tool("fakejq", install=f"script:{SCRIPT}"))
    code, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert code == 4
    assert not (isolated_environment / "script-ran").exists()
    assert "skipped (needs an interactive confirmation): fakejq" in out


def test_a_script_without_tty_and_without_yes_is_skipped_not_confirmed(
    capsys, monkeypatch, fake_tools
):
    no_tty(monkeypatch)
    declare("work", Tool("fakejq", install=f"script:{SCRIPT}"))
    code, out, _ = run(capsys, "doctor", "--fix")
    assert code == 4
    assert "skipped" in out


def test_a_script_runs_after_the_confirmation_on_a_tty(
    capsys, monkeypatch, fake_tools, isolated_environment
):
    asked = tty(monkeypatch, "y")
    declare("work", Tool("fakejq", install=f"script:{SCRIPT}"))
    code, out, _ = run(capsys, "doctor", "--fix")
    assert code == 4  # the script installs no fakejq, doctor checks again
    assert (isolated_environment / "script-ran").exists()
    assert len(asked) == 1
    assert SCRIPT_SHOWN in asked[0]


def test_a_script_needs_the_tty_confirmation_even_with_yes(
    capsys, monkeypatch, fake_tools, fake_managers, isolated_environment
):
    asked = tty(monkeypatch, "y")
    fake_managers.provides("brew", "fakertk", tool="fakertk", output="fakertk 1.0.0")
    declare(
        "work",
        Tool("fakertk", install="brew:fakertk"),
        Tool("fakejq", install=f"script:{SCRIPT}"),
    )
    run(capsys, "doctor", "--fix", "--yes")
    assert len(asked) == 1
    assert "install fakertk" not in asked[0]
    assert "script-ran" in asked[0]
    assert (isolated_environment / "script-ran").exists()
    assert ["brew", "install", "fakertk"] in fake_managers.calls()


def test_a_declined_script_with_yes_is_skipped_but_managers_run(
    capsys, monkeypatch, fake_tools, fake_managers, isolated_environment
):
    tty(monkeypatch, "n")
    fake_managers.provides("brew", "fakertk", tool="fakertk", output="fakertk 1.0.0")
    declare(
        "work",
        Tool("fakertk", install="brew:fakertk"),
        Tool("fakejq", install=f"script:{SCRIPT}"),
    )
    code, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert code == 4
    assert not (isolated_environment / "script-ran").exists()
    assert ["brew", "install", "fakertk"] in fake_managers.calls()
    assert "skipped" in out


def test_a_script_with_the_manager_confirmation_declined_runs_nothing(
    capsys, monkeypatch, fake_tools, fake_managers, isolated_environment
):
    tty(monkeypatch, "n")
    fake_managers.provides("brew", "fakertk", tool="fakertk", output="fakertk 1.0.0")
    declare(
        "work",
        Tool("fakertk", install="brew:fakertk"),
        Tool("fakejq", install=f"script:{SCRIPT}"),
    )
    code, _, err = run(capsys, "doctor", "--fix")
    assert code == 0
    assert "cancelled" in err
    assert not (isolated_environment / "script-ran").exists()
    assert ["brew", "install", "fakertk"] not in fake_managers.calls()


def test_dry_run_prints_every_command_and_runs_nothing(
    capsys, monkeypatch, fake_tools, fake_managers, isolated_environment
):
    no_tty(monkeypatch)
    declare(
        "work",
        Tool("fakertk", install="brew:fakertk"),
        Tool("fakejq", install=f"script:{SCRIPT}"),
    )
    code, out, _ = run(capsys, "doctor", "--fix", "--dry-run")
    assert code == 0
    assert f"would run: {brew_path()} install fakertk" in out
    assert f"would run: {SCRIPT_SHOWN}" in out
    assert fake_managers.calls() == [["brew", "list", "fakertk"]]
    assert not (isolated_environment / "script-ran").exists()


def test_the_first_failing_command_stops_the_fix(capsys, fake_tools, fake_managers):
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    fake_managers.provides("npm", "faketool", tool="faketool", output="faketool 2.0.0")
    fake_managers.fail("brew", "fakejq")
    declare(
        "work",
        Tool("fakejq", install="brew:fakejq"),
        Tool("faketool", install="npm:faketool"),
    )
    code, _, err = run(capsys, "doctor", "--fix", "--yes")
    assert code == 1
    assert f"{brew_path()} install fakejq" in err
    assert "forced failure for fakejq" in err
    assert all(call[0] != "npm" for call in fake_managers.calls())


def test_fix_json_prints_one_document_with_the_final_state(capsys, fake_tools, fake_managers):
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", install="brew:fakejq"))
    code, out, err = run(capsys, "doctor", "--fix", "--json", "--yes")
    assert code == 0
    assert json.loads(out)["ok"] is True
    assert f"{brew_path()} install fakejq" in err


def test_fix_json_never_prompts_so_a_script_is_skipped(
    capsys, monkeypatch, fake_tools, isolated_environment
):
    asked = tty(monkeypatch, "y")
    declare("work", Tool("fakejq", install=f"script:{SCRIPT}"))
    code, out, _ = run(capsys, "doctor", "--fix", "--json", "--yes")
    assert code == 4
    assert asked == []
    assert not (isolated_environment / "script-ran").exists()
    assert json.loads(out)["ok"] is False


def test_help_documents_recipes_confirmations_and_exit_codes(capsys):
    _, out, _ = run(capsys, "doctor", "--help")
    for text in ("brew:<formula>", "script:<command>", "--dry-run", "--fix", "--json", "--yes"):
        assert text in out
    assert "even with --yes" in out
    assert "  3  confirmation required" in out
    assert "  4  drift" in out


def test_fix_lists_the_tools_before_running_the_commands(capsys, fake_tools, fake_managers):
    fake_managers.provides("brew", "fakejq", tool="fakejq", output="fakejq-1.7")
    declare("work", Tool("fakejq", install="brew:fakejq"))
    _, out, _ = run(capsys, "doctor", "--fix", "--yes")
    assert out.index("missing  fakejq") < out.index("run: ")


def test_fix_commands_get_a_closed_stdin(capsys, monkeypatch, fake_tools, isolated_environment):
    tty(monkeypatch, "y")
    declare("work", Tool("fakejq", install='script:cat > "$HOME/stdin-seen"'))
    read_end, write_end = os.pipe()
    os.write(write_end, b"leaked")
    os.close(write_end)
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        run(capsys, "doctor", "--fix")
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(read_end)
    assert (isolated_environment / "stdin-seen").read_text() == ""


def test_dry_run_json_prints_the_planned_commands_and_nothing_else(
    capsys, monkeypatch, fake_tools, fake_managers
):
    tty(monkeypatch, "y")
    declare(
        "work",
        Tool("fakertk", install="brew:fakertk"),
        Tool("fakejq", install=f"script:{SCRIPT}"),
        Tool("faketool"),
    )
    code, out, err = run(capsys, "doctor", "--fix", "--dry-run", "--json", "--yes")
    assert code == 0
    assert err == ""
    assert json.loads(out) == {
        "planned": [{"name": "fakertk", "command": f"{brew_path()} install fakertk"}],
        "skipped": ["fakejq"],
    }
