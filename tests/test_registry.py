import argparse

import pytest

from claude_sync import registry
from claude_sync.cli import build_parser, main
from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
from claude_sync.exit_codes import ExitCode
from claude_sync.registry import Command


def subparser(name):
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError("no subparsers")


def flags(parser):
    return {opt for action in parser._actions for opt in action.option_strings}


@pytest.mark.parametrize("command", registry.COMMANDS, ids=lambda c: c.name)
def test_every_command_documents_itself(command):
    assert command.summary.strip()
    assert command.description.strip()
    assert command.examples
    assert command.exit_codes


@pytest.mark.parametrize("command", registry.COMMANDS, ids=lambda c: c.name)
def test_flags_follow_the_kind(command):
    found = flags(subparser(command.name))
    if command.kind == "read":
        assert "--json" in found
    # a mutating command may add --json itself (doctor reports before and after a fix)
    assert ({"--dry-run", "--yes"} <= found) == (command.kind == "mutate")


def fake(kind, run, name="fake"):
    return Command(
        name=name,
        summary="s",
        description="d",
        examples=[("claude-sync fake", "e")],
        exit_codes=[ExitCode.OK],
        kind=kind,
        configure=lambda p: None,
        run=run,
    )


def test_mutate_command_gets_dry_run_and_yes_into_its_context(monkeypatch, capsys):
    seen = []

    def run(args, ctx):
        seen.append((ctx.dry_run, ctx.yes))
        return 0

    monkeypatch.setattr(registry, "COMMANDS", [fake("mutate", run)])
    assert main(["fake", "--dry-run", "--yes"]) == 0
    assert seen == [(True, True)]


def test_confirmation_required_maps_to_exit_3(monkeypatch, capsys):
    def run(args, ctx):
        ctx.confirm("Overwrite everything?")
        return 0

    monkeypatch.setattr(registry, "COMMANDS", [fake("mutate", run)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["fake"]) == 3
    err = capsys.readouterr().err
    assert "Overwrite everything?" in err and "rerun with --yes" in err


def test_yes_skips_the_confirmation(monkeypatch):
    monkeypatch.setattr(
        registry, "COMMANDS", [fake("mutate", lambda a, ctx: int(not ctx.confirm("q")))]
    )
    assert main(["fake", "--yes"]) == 0


def test_claude_sync_error_maps_to_exit_1(monkeypatch, capsys):
    def run(args, ctx):
        raise ClaudeSyncError("boom")

    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
    assert main(["fake"]) == 1
    err = capsys.readouterr().err
    assert err == "claude-sync: error: boom\n"


def test_traceback_only_with_debug(monkeypatch, capsys):
    def run(args, ctx):
        raise ClaudeSyncError("boom")

    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
    monkeypatch.setenv("CLAUDE_SYNC_DEBUG", "1")
    main(["fake"])
    assert "Traceback" in capsys.readouterr().err


def test_confirmation_required_error_is_not_swallowed_as_generic(monkeypatch, capsys):
    def run(args, ctx):
        raise ConfirmationRequired("q")

    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
    assert main(["fake"]) == 3
