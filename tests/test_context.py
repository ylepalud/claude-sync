import json

import pytest

from claude_sync.context import Context
from claude_sync.errors import ConfirmationRequired


def make(**kw):
    base = {"json": False, "dry_run": False, "yes": False, "stdin_is_tty": False}
    return Context(**{**base, **kw})


def test_confirm_is_true_with_yes():
    assert make(yes=True).confirm("proceed?") is True


def test_confirm_without_yes_and_without_tty_raises():
    with pytest.raises(ConfirmationRequired, match="proceed\\?"):
        make().confirm("proceed?")


def test_confirm_prompts_on_a_tty(monkeypatch):
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "y")
    assert make(stdin_is_tty=True).confirm("proceed?") is True
    assert "proceed?" in asked[0]


def test_confirm_on_a_tty_declines_by_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert make(stdin_is_tty=True).confirm("proceed?") is False


def test_emit_prints_text_by_default(capsys):
    make().emit({"a": 1}, "hello")
    assert capsys.readouterr().out == "hello\n"


def test_emit_prints_only_json_with_json(capsys):
    make(json=True).emit({"a": 1}, "hello")
    assert json.loads(capsys.readouterr().out) == {"a": 1}
