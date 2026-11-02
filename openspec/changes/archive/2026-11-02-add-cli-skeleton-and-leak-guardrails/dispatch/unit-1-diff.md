diff --git a/.gitignore b/.gitignore
index b081616..5afb24f 100644
--- a/.gitignore
+++ b/.gitignore
@@ -15,3 +15,6 @@ build/
 *.egg-info/
 
 .DS_Store
+# OpenSpec dispatch scratch space
+/openspec/changes/*/dispatch/
+denylist.txt
diff --git a/install.sh b/install.sh
new file mode 100755
index 0000000..f83ee0d
--- /dev/null
+++ b/install.sh
@@ -0,0 +1,11 @@
+#!/usr/bin/env bash
+set -euo pipefail
+
+if ! command -v uv >/dev/null 2>&1; then
+  echo "install.sh: uv is required but was not found on PATH." >&2
+  echo "Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
+  exit 1
+fi
+
+uv tool install --force "${CLAUDE_SYNC_SOURCE:-git+https://github.com/ylepalud/claude-sync}"
+claude-sync --version
diff --git a/pyproject.toml b/pyproject.toml
new file mode 100644
index 0000000..8475b56
--- /dev/null
+++ b/pyproject.toml
@@ -0,0 +1,29 @@
+[project]
+name = "claude-sync"
+version = "0.1.0"
+description = "Keep Claude Code configuration in sync across machines"
+readme = "README.md"
+license = "MIT"
+requires-python = ">=3.11"
+dependencies = []
+
+[project.scripts]
+claude-sync = "claude_sync.cli:entry"
+
+[build-system]
+requires = ["hatchling"]
+build-backend = "hatchling.build"
+
+[tool.hatch.build.targets.wheel]
+packages = ["src/claude_sync"]
+
+[dependency-groups]
+dev = ["pytest", "ruff"]
+
+[tool.ruff]
+target-version = "py311"
+line-length = 100
+extend-include = ["scripts/check-denylist"]
+
+[tool.ruff.lint]
+select = ["E", "F", "I", "B", "UP"]
diff --git a/src/claude_sync/__init__.py b/src/claude_sync/__init__.py
new file mode 100644
index 0000000..1c592bf
--- /dev/null
+++ b/src/claude_sync/__init__.py
@@ -0,0 +1,3 @@
+from importlib.metadata import version
+
+__version__ = version("claude-sync")
diff --git a/src/claude_sync/__main__.py b/src/claude_sync/__main__.py
new file mode 100644
index 0000000..91b755d
--- /dev/null
+++ b/src/claude_sync/__main__.py
@@ -0,0 +1,3 @@
+from claude_sync.cli import entry
+
+raise SystemExit(entry())
diff --git a/src/claude_sync/cli.py b/src/claude_sync/cli.py
new file mode 100644
index 0000000..7e1b2a6
--- /dev/null
+++ b/src/claude_sync/cli.py
@@ -0,0 +1,67 @@
+from __future__ import annotations
+
+import argparse
+import os
+import sys
+import traceback
+
+from claude_sync import __version__, registry
+from claude_sync.context import Context
+from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
+from claude_sync.exit_codes import ExitCode
+
+DESCRIPTION = "Keep Claude Code configuration in sync across machines."
+EXAMPLES = [
+    ("claude-sync --version", "print the installed version"),
+    ("claude-sync help --all", "print the help of every command"),
+]
+
+
+def build_parser() -> argparse.ArgumentParser:
+    parser = argparse.ArgumentParser(
+        prog="claude-sync",
+        description=DESCRIPTION,
+        epilog=registry.render_epilog(EXAMPLES, list(ExitCode)),
+        formatter_class=argparse.RawDescriptionHelpFormatter,
+    )
+    parser.add_argument("--version", action="version", version=f"claude-sync {__version__}")
+    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
+    for command in registry.COMMANDS:
+        registry.add_command_parser(subparsers, command)
+    return parser
+
+
+def main(argv: list[str] | None = None) -> int:
+    parser = build_parser()
+    try:
+        args = parser.parse_args(argv)
+    except SystemExit as e:
+        return int(e.code or 0)
+    if args.command is None:
+        parser.print_help()
+        return int(ExitCode.OK)
+    ctx = Context(
+        json=getattr(args, "json", False),
+        dry_run=getattr(args, "dry_run", False),
+        yes=getattr(args, "yes", False),
+        stdin_is_tty=sys.stdin.isatty(),
+    )
+    try:
+        return int(args.command_spec.run(args, ctx))
+    except ConfirmationRequired as e:
+        _report(e)
+        print("rerun with --yes", file=sys.stderr)
+        return int(ExitCode.CONFIRMATION_REQUIRED)
+    except ClaudeSyncError as e:
+        _report(e)
+        return int(ExitCode.ERROR)
+
+
+def _report(error: ClaudeSyncError) -> None:
+    if os.environ.get("CLAUDE_SYNC_DEBUG") == "1":
+        traceback.print_exc()
+    print(f"claude-sync: error: {error}", file=sys.stderr)
+
+
+def entry() -> None:
+    sys.exit(main())
diff --git a/src/claude_sync/commands/__init__.py b/src/claude_sync/commands/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/src/claude_sync/commands/help.py b/src/claude_sync/commands/help.py
new file mode 100644
index 0000000..aba74cb
--- /dev/null
+++ b/src/claude_sync/commands/help.py
@@ -0,0 +1,60 @@
+from __future__ import annotations
+
+import argparse
+
+from claude_sync import registry
+from claude_sync.context import Context
+from claude_sync.exit_codes import ExitCode
+from claude_sync.registry import Command
+
+RULE = "-" * 72
+
+
+def configure(parser: argparse.ArgumentParser) -> None:
+    parser.add_argument(
+        "topic",
+        nargs="?",
+        metavar="COMMAND",
+        choices=[c.name for c in registry.COMMANDS],
+        help="command to describe (default: the top-level help)",
+    )
+    parser.add_argument("--all", action="store_true", help="print the help of every command")
+
+
+def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
+    for action in parser._actions:
+        if isinstance(action, argparse._SubParsersAction):
+            return dict(action.choices)
+    return {}
+
+
+def run(args: argparse.Namespace, ctx: Context) -> int:
+    from claude_sync.cli import build_parser
+
+    parser = build_parser()
+    subparsers = _subparsers(parser)
+    if args.all:
+        blocks = [parser.format_help()]
+        blocks += [subparsers[c.name].format_help() for c in registry.COMMANDS]
+        print(f"\n{RULE}\n\n".join(blocks), end="")
+    elif args.topic:
+        print(subparsers[args.topic].format_help(), end="")
+    else:
+        print(parser.format_help(), end="")
+    return int(ExitCode.OK)
+
+
+COMMAND = Command(
+    name="help",
+    summary="show the help of a command or of every command",
+    description="Show the help of one command, or with --all the help of every command.",
+    examples=[
+        ("claude-sync help", "print the top-level help"),
+        ("claude-sync help version", "same output as `claude-sync version --help`"),
+        ("claude-sync help --all", "print the top-level help then each command's help"),
+    ],
+    exit_codes=[ExitCode.OK, ExitCode.USAGE],
+    kind="doc",
+    configure=configure,
+    run=run,
+)
diff --git a/src/claude_sync/commands/version.py b/src/claude_sync/commands/version.py
new file mode 100644
index 0000000..b5bd969
--- /dev/null
+++ b/src/claude_sync/commands/version.py
@@ -0,0 +1,36 @@
+from __future__ import annotations
+
+import argparse
+import platform
+
+from claude_sync import __version__
+from claude_sync.context import Context
+from claude_sync.exit_codes import ExitCode
+from claude_sync.registry import Command
+
+
+def configure(parser: argparse.ArgumentParser) -> None:
+    pass
+
+
+def run(args: argparse.Namespace, ctx: Context) -> int:
+    ctx.emit(
+        {"version": __version__, "python": platform.python_version()},
+        f"claude-sync {__version__}",
+    )
+    return int(ExitCode.OK)
+
+
+COMMAND = Command(
+    name="version",
+    summary="print the installed version",
+    description="Print the installed claude-sync version.",
+    examples=[
+        ("claude-sync version", "print `claude-sync <version>`"),
+        ("claude-sync version --json", "print the version and the Python version as JSON"),
+    ],
+    exit_codes=[ExitCode.OK],
+    kind="read",
+    configure=configure,
+    run=run,
+)
diff --git a/src/claude_sync/context.py b/src/claude_sync/context.py
new file mode 100644
index 0000000..fcf6ce7
--- /dev/null
+++ b/src/claude_sync/context.py
@@ -0,0 +1,24 @@
+from __future__ import annotations
+
+import json
+from dataclasses import dataclass
+
+from claude_sync.errors import ConfirmationRequired
+
+
+@dataclass(frozen=True)
+class Context:
+    json: bool
+    dry_run: bool
+    yes: bool
+    stdin_is_tty: bool
+
+    def confirm(self, question: str) -> bool:
+        if self.yes:
+            return True
+        if self.stdin_is_tty:
+            return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
+        raise ConfirmationRequired(question)
+
+    def emit(self, data: dict, text: str) -> None:
+        print(json.dumps(data) if self.json else text)
diff --git a/src/claude_sync/errors.py b/src/claude_sync/errors.py
new file mode 100644
index 0000000..576bb67
--- /dev/null
+++ b/src/claude_sync/errors.py
@@ -0,0 +1,6 @@
+class ClaudeSyncError(Exception):
+    """A failure to report to the user without a traceback."""
+
+
+class ConfirmationRequired(ClaudeSyncError):
+    """A confirmation is needed but cannot be asked (no --yes, no TTY)."""
diff --git a/src/claude_sync/exit_codes.py b/src/claude_sync/exit_codes.py
new file mode 100644
index 0000000..51f8f25
--- /dev/null
+++ b/src/claude_sync/exit_codes.py
@@ -0,0 +1,19 @@
+from enum import IntEnum
+
+
+class ExitCode(IntEnum):
+    """Exit codes shared by every command."""
+
+    description: str
+
+    OK = (0, "success")
+    ERROR = (1, "runtime error")
+    USAGE = (2, "usage error")
+    CONFIRMATION_REQUIRED = (3, "confirmation required but not given (rerun with --yes)")
+    DRIFT = (4, "drift detected: state differs from what is declared")
+
+    def __new__(cls, value: int, description: str) -> "ExitCode":
+        member = int.__new__(cls, value)
+        member._value_ = value
+        member.description = description
+        return member
diff --git a/src/claude_sync/registry.py b/src/claude_sync/registry.py
new file mode 100644
index 0000000..efce640
--- /dev/null
+++ b/src/claude_sync/registry.py
@@ -0,0 +1,73 @@
+"""Command registry: one `Command` per CLI command, and the parser builder."""
+
+from __future__ import annotations
+
+import argparse
+from collections.abc import Callable, Sequence
+from dataclasses import dataclass
+from typing import TYPE_CHECKING, Any, Literal
+
+from claude_sync.exit_codes import ExitCode
+
+if TYPE_CHECKING:
+    from claude_sync.context import Context
+
+COMMAND_MODULES = ("version", "help")
+
+
+@dataclass(frozen=True)
+class Command:
+    name: str
+    summary: str
+    description: str
+    examples: list[tuple[str, str]]
+    exit_codes: list[ExitCode]
+    kind: Literal["read", "mutate", "doc"]
+    configure: Callable[[argparse.ArgumentParser], None]
+    run: Callable[[argparse.Namespace, Context], int]
+
+
+def render_epilog(examples: Sequence[tuple[str, str]], exit_codes: Sequence[ExitCode]) -> str:
+    lines = ["Examples:"]
+    for command_line, explanation in examples:
+        lines.append(f"  $ {command_line}")
+        lines.append(f"      {explanation}")
+    lines.append("")
+    lines.append("Exit codes:")
+    for code in exit_codes:
+        lines.append(f"  {int(code)}  {code.description}")
+    return "\n".join(lines)
+
+
+def add_command_parser(subparsers: Any, command: Command) -> argparse.ArgumentParser:
+    """Create the subparser of `command`, adding the flags its kind requires."""
+    parser = subparsers.add_parser(
+        command.name,
+        help=command.summary,
+        description=command.description,
+        epilog=render_epilog(command.examples, command.exit_codes),
+        formatter_class=argparse.RawDescriptionHelpFormatter,
+    )
+    command.configure(parser)
+    if command.kind == "read":
+        parser.add_argument("--json", action="store_true", help="print one JSON document")
+    elif command.kind == "mutate":
+        parser.add_argument(
+            "--dry-run", action="store_true", help="print the planned actions, change nothing"
+        )
+        parser.add_argument("--yes", action="store_true", help="answer every confirmation")
+    parser.set_defaults(command_spec=command)
+    return parser
+
+
+def __getattr__(name: str) -> list[Command]:
+    # Lazy so that command modules can import `Command` from here without a cycle.
+    if name == "COMMANDS":
+        from importlib import import_module
+
+        commands = [
+            import_module(f"claude_sync.commands.{module}").COMMAND for module in COMMAND_MODULES
+        ]
+        globals()["COMMANDS"] = commands
+        return commands
+    raise AttributeError(name)
diff --git a/tests/conftest.py b/tests/conftest.py
new file mode 100644
index 0000000..5f010ff
--- /dev/null
+++ b/tests/conftest.py
@@ -0,0 +1,14 @@
+import pytest
+
+
+@pytest.fixture(autouse=True)
+def isolated_environment(tmp_path, monkeypatch):
+    """Keep every test away from the real home, git config and Keychain."""
+    home = tmp_path / "home"
+    home.mkdir()
+    monkeypatch.setenv("HOME", str(home))
+    for name in ("XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "DENYLIST"):
+        monkeypatch.delenv(name, raising=False)
+    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
+    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
+    return home
diff --git a/tests/test_cli.py b/tests/test_cli.py
new file mode 100644
index 0000000..5fd0f4d
--- /dev/null
+++ b/tests/test_cli.py
@@ -0,0 +1,83 @@
+import json
+import platform
+
+from claude_sync import registry
+from claude_sync.cli import main
+
+
+def run(capsys, *argv):
+    code = main(list(argv))
+    out = capsys.readouterr()
+    return code, out.out, out.err
+
+
+def test_version_flag(capsys):
+    code, out, _ = run(capsys, "--version")
+    assert (code, out) == (0, "claude-sync 0.1.0\n")
+
+
+def test_no_argument_prints_top_level_help(capsys):
+    code, out, _ = run(capsys)
+    assert code == 0
+    assert out.startswith("usage: claude-sync")
+    assert "Examples:" in out and "Exit codes:" in out
+
+
+def test_unknown_command_is_a_usage_error(capsys):
+    code, out, err = run(capsys, "does-not-exist")
+    assert code == 2
+    assert "usage: claude-sync" in err
+    assert out == ""
+
+
+def test_version_json_prints_only_a_json_object(capsys):
+    code, out, _ = run(capsys, "version", "--json")
+    assert code == 0
+    assert json.loads(out) == {"version": "0.1.0", "python": platform.python_version()}
+
+
+def test_version_text(capsys):
+    code, out, _ = run(capsys, "version")
+    assert (code, out) == (0, "claude-sync 0.1.0\n")
+
+
+def test_help_of_a_command_equals_its_dash_dash_help(capsys):
+    _, via_help, _ = run(capsys, "help", "version")
+    _, via_flag, _ = run(capsys, "version", "--help")
+    assert via_help == via_flag
+    assert via_help != ""
+
+
+def test_help_all_has_top_level_and_every_command(capsys):
+    code, out, _ = run(capsys, "help", "--all")
+    assert code == 0
+    assert "usage: claude-sync [-h]" in out
+    for command in registry.COMMANDS:
+        assert f"usage: claude-sync {command.name}" in out
+
+
+def test_help_all_is_in_registry_order(capsys):
+    _, out, _ = run(capsys, "help", "--all")
+    positions = [out.index(f"usage: claude-sync {c.name}") for c in registry.COMMANDS]
+    assert positions == sorted(positions)
+
+
+def test_help_of_unknown_command_is_a_usage_error(capsys):
+    code, _, err = run(capsys, "help", "nope")
+    assert code == 2
+    assert "nope" in err
+
+
+def test_subcommand_help_has_examples_and_exit_codes(capsys):
+    code, out, _ = run(capsys, "version", "--help")
+    assert code == 0
+    assert out.startswith("usage: claude-sync version")
+    assert "Examples:" in out and "Exit codes:" in out
+    assert "  $ claude-sync version" in out
+    assert "  0  success" in out
+
+
+def test_help_rejects_json(capsys):
+    code, _, err = run(capsys, "help", "--json")
+    assert code == 2
+    assert "usage: claude-sync" in err and "--json" in err
diff --git a/tests/test_context.py b/tests/test_context.py
new file mode 100644
index 0000000..bd810d3
--- /dev/null
+++ b/tests/test_context.py
@@ -0,0 +1,42 @@
+import json
+
+import pytest
+
+from claude_sync.context import Context
+from claude_sync.errors import ConfirmationRequired
+
+
+def make(**kw):
+    base = {"json": False, "dry_run": False, "yes": False, "stdin_is_tty": False}
+    return Context(**{**base, **kw})
+
+
+def test_confirm_is_true_with_yes():
+    assert make(yes=True).confirm("proceed?") is True
+
+
+def test_confirm_without_yes_and_without_tty_raises():
+    with pytest.raises(ConfirmationRequired, match="proceed\\?"):
+        make().confirm("proceed?")
+
+
+def test_confirm_prompts_on_a_tty(monkeypatch):
+    asked = []
+    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "y")
+    assert make(stdin_is_tty=True).confirm("proceed?") is True
+    assert "proceed?" in asked[0]
+
+
+def test_confirm_on_a_tty_declines_by_default(monkeypatch):
+    monkeypatch.setattr("builtins.input", lambda prompt: "")
+    assert make(stdin_is_tty=True).confirm("proceed?") is False
+
+
+def test_emit_prints_text_by_default(capsys):
+    make().emit({"a": 1}, "hello")
+    assert capsys.readouterr().out == "hello\n"
+
+
+def test_emit_prints_only_json_with_json(capsys):
+    make(json=True).emit({"a": 1}, "hello")
+    assert json.loads(capsys.readouterr().out) == {"a": 1}
diff --git a/tests/test_exit_codes.py b/tests/test_exit_codes.py
new file mode 100644
index 0000000..113b980
--- /dev/null
+++ b/tests/test_exit_codes.py
@@ -0,0 +1,21 @@
+from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
+from claude_sync.exit_codes import ExitCode
+
+
+def test_exit_code_values_are_the_documented_ones():
+    assert {c.name: int(c) for c in ExitCode} == {
+        "OK": 0,
+        "ERROR": 1,
+        "USAGE": 2,
+        "CONFIRMATION_REQUIRED": 3,
+        "DRIFT": 4,
+    }
+
+
+def test_every_exit_code_has_a_one_line_description():
+    for code in ExitCode:
+        assert code.description and "\n" not in code.description
+
+
+def test_confirmation_required_is_a_claude_sync_error():
+    assert issubclass(ConfirmationRequired, ClaudeSyncError)
diff --git a/tests/test_isolation.py b/tests/test_isolation.py
new file mode 100644
index 0000000..ac6e6c3
--- /dev/null
+++ b/tests/test_isolation.py
@@ -0,0 +1,16 @@
+import os
+from pathlib import Path
+
+
+def test_home_is_a_temporary_directory(tmp_path):
+    assert Path(os.environ["HOME"]).is_relative_to(tmp_path)
+
+
+def test_config_locations_are_unset():
+    for name in ("XDG_CONFIG_HOME", "CLAUDE_CONFIG_DIR", "DENYLIST"):
+        assert name not in os.environ
+
+
+def test_git_global_and_system_config_are_disabled():
+    assert os.environ["GIT_CONFIG_GLOBAL"] == "/dev/null"
+    assert os.environ["GIT_CONFIG_SYSTEM"] == "/dev/null"
diff --git a/tests/test_package.py b/tests/test_package.py
new file mode 100644
index 0000000..f57d43d
--- /dev/null
+++ b/tests/test_package.py
@@ -0,0 +1,16 @@
+import subprocess
+import sys
+
+import claude_sync
+
+
+def test_version_is_the_packaged_version():
+    assert claude_sync.__version__ == "0.1.0"
+
+
+def test_python_dash_m_runs_the_cli():
+    result = subprocess.run(
+        [sys.executable, "-m", "claude_sync", "--version"], capture_output=True, text=True
+    )
+    assert result.stdout == "claude-sync 0.1.0\n"
+    assert result.returncode == 0
diff --git a/tests/test_registry.py b/tests/test_registry.py
new file mode 100644
index 0000000..7fc3fff
--- /dev/null
+++ b/tests/test_registry.py
@@ -0,0 +1,108 @@
+import argparse
+
+import pytest
+
+from claude_sync import registry
+from claude_sync.cli import build_parser, main
+from claude_sync.errors import ClaudeSyncError, ConfirmationRequired
+from claude_sync.exit_codes import ExitCode
+from claude_sync.registry import Command
+
+
+def subparser(name):
+    parser = build_parser()
+    for action in parser._actions:
+        if isinstance(action, argparse._SubParsersAction):
+            return action.choices[name]
+    raise AssertionError("no subparsers")
+
+
+def flags(parser):
+    return {opt for action in parser._actions for opt in action.option_strings}
+
+
+@pytest.mark.parametrize("command", registry.COMMANDS, ids=lambda c: c.name)
+def test_every_command_documents_itself(command):
+    assert command.summary.strip()
+    assert command.description.strip()
+    assert command.examples
+    assert command.exit_codes
+
+
+@pytest.mark.parametrize("command", registry.COMMANDS, ids=lambda c: c.name)
+def test_flags_follow_the_kind(command):
+    found = flags(subparser(command.name))
+    assert ("--json" in found) == (command.kind == "read")
+    assert ({"--dry-run", "--yes"} <= found) == (command.kind == "mutate")
+
+
+def fake(kind, run, name="fake"):
+    return Command(
+        name=name,
+        summary="s",
+        description="d",
+        examples=[("claude-sync fake", "e")],
+        exit_codes=[ExitCode.OK],
+        kind=kind,
+        configure=lambda p: None,
+        run=run,
+    )
+
+
+def test_mutate_command_gets_dry_run_and_yes_into_its_context(monkeypatch, capsys):
+    seen = []
+
+    def run(args, ctx):
+        seen.append((ctx.dry_run, ctx.yes))
+        return 0
+
+    monkeypatch.setattr(registry, "COMMANDS", [fake("mutate", run)])
+    assert main(["fake", "--dry-run", "--yes"]) == 0
+    assert seen == [(True, True)]
+
+
+def test_confirmation_required_maps_to_exit_3(monkeypatch, capsys):
+    def run(args, ctx):
+        ctx.confirm("Overwrite everything?")
+        return 0
+
+    monkeypatch.setattr(registry, "COMMANDS", [fake("mutate", run)])
+    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
+    assert main(["fake"]) == 3
+    err = capsys.readouterr().err
+    assert "Overwrite everything?" in err and "rerun with --yes" in err
+
+
+def test_yes_skips_the_confirmation(monkeypatch):
+    monkeypatch.setattr(
+        registry, "COMMANDS", [fake("mutate", lambda a, ctx: int(not ctx.confirm("q")))]
+    )
+    assert main(["fake", "--yes"]) == 0
+
+
+def test_claude_sync_error_maps_to_exit_1(monkeypatch, capsys):
+    def run(args, ctx):
+        raise ClaudeSyncError("boom")
+
+    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
+    assert main(["fake"]) == 1
+    err = capsys.readouterr().err
+    assert err == "claude-sync: error: boom\n"
+
+
+def test_traceback_only_with_debug(monkeypatch, capsys):
+    def run(args, ctx):
+        raise ClaudeSyncError("boom")
+
+    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
+    monkeypatch.setenv("CLAUDE_SYNC_DEBUG", "1")
+    main(["fake"])
+    assert "Traceback" in capsys.readouterr().err
+
+
+def test_confirmation_required_error_is_not_swallowed_as_generic(monkeypatch, capsys):
+    def run(args, ctx):
+        raise ConfirmationRequired("q")
+
+    monkeypatch.setattr(registry, "COMMANDS", [fake("read", run)])
+    assert main(["fake"]) == 3
