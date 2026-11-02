import json
import platform

from claude_sync import registry
from claude_sync.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version_flag(capsys):
    code, out, _ = run(capsys, "--version")
    assert (code, out) == (0, "claude-sync 0.1.0\n")


def test_no_argument_prints_top_level_help(capsys):
    code, out, _ = run(capsys)
    assert code == 0
    assert out.startswith("usage: claude-sync")
    assert "Examples:" in out and "Exit codes:" in out


def test_unknown_command_is_a_usage_error(capsys):
    code, out, err = run(capsys, "does-not-exist")
    assert code == 2
    assert "usage: claude-sync" in err
    assert out == ""


def test_version_json_prints_only_a_json_object(capsys):
    code, out, _ = run(capsys, "version", "--json")
    assert code == 0
    assert json.loads(out) == {"version": "0.1.0", "python": platform.python_version()}


def test_version_text(capsys):
    code, out, _ = run(capsys, "version")
    assert (code, out) == (0, "claude-sync 0.1.0\n")


def test_help_of_a_command_equals_its_dash_dash_help(capsys):
    _, via_help, _ = run(capsys, "help", "version")
    _, via_flag, _ = run(capsys, "version", "--help")
    assert via_help == via_flag
    assert via_help != ""


def test_help_all_has_top_level_and_every_command(capsys):
    code, out, _ = run(capsys, "help", "--all")
    assert code == 0
    assert "usage: claude-sync [-h]" in out
    for command in registry.COMMANDS:
        assert f"usage: claude-sync {command.name}" in out


def test_help_all_is_in_registry_order(capsys):
    _, out, _ = run(capsys, "help", "--all")
    positions = [out.index(f"usage: claude-sync {c.name}") for c in registry.COMMANDS]
    assert positions == sorted(positions)


def test_registry_order_is_stable():
    assert [c.name for c in registry.COMMANDS] == [
        "version",
        "help",
        "which",
        "list",
        "config",
        "map",
        "unmap",
        "set-default",
        "shell-init",
        "profile",
        "import",
    ]


def test_help_all_separates_blocks_with_a_rule_line(capsys):
    _, out, _ = run(capsys, "help", "--all")
    rule = "\n" + "-" * 72 + "\n"
    assert out.count(rule) == len(registry.COMMANDS)


def test_help_of_unknown_command_is_a_usage_error(capsys):
    code, _, err = run(capsys, "help", "nope")
    assert code == 2
    assert "nope" in err


def test_subcommand_help_has_examples_and_exit_codes(capsys):
    code, out, _ = run(capsys, "version", "--help")
    assert code == 0
    assert out.startswith("usage: claude-sync version")
    assert "Examples:" in out and "Exit codes:" in out
    assert "  $ claude-sync version" in out
    assert "  0  success" in out


def test_help_rejects_json(capsys):
    code, _, err = run(capsys, "help", "--json")
    assert code == 2
    assert "usage: claude-sync" in err and "--json" in err


def _install_failing_command(monkeypatch):
    def boom(args, ctx):
        raise RuntimeError("secret detail")

    fake = registry.Command(
        name="boom",
        summary="fails",
        description="fails",
        examples=[],
        exit_codes=[],
        kind="doc",
        configure=lambda parser: None,
        run=boom,
    )
    monkeypatch.setattr(registry, "COMMANDS", [*registry.COMMANDS, fake])


def test_unexpected_exception_prints_a_fixed_message_and_exits_1(capsys, monkeypatch):
    monkeypatch.delenv("CLAUDE_SYNC_DEBUG", raising=False)
    _install_failing_command(monkeypatch)
    code, _, err = run(capsys, "boom")
    assert code == 1
    assert err == (
        "claude-sync: error: internal error, rerun with CLAUDE_SYNC_DEBUG=1 for details\n"
    )
    assert "Traceback" not in err and "secret detail" not in err


def test_unexpected_exception_shows_the_traceback_in_debug_mode(capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_SYNC_DEBUG", "1")
    _install_failing_command(monkeypatch)
    code, _, err = run(capsys, "boom")
    assert code == 1
    assert "Traceback" in err
    assert "claude-sync: error: internal error" in err
