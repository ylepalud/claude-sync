from __future__ import annotations

import json
from dataclasses import dataclass

from claude_sync.errors import ConfirmationRequired


@dataclass(frozen=True)
class Context:
    json: bool
    dry_run: bool
    yes: bool
    stdin_is_tty: bool

    def confirm(self, question: str) -> bool:
        if self.yes:
            return True
        if self.stdin_is_tty:
            return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
        raise ConfirmationRequired(question)

    def emit(self, data: dict, text: str) -> None:
        print(json.dumps(data) if self.json else text)
