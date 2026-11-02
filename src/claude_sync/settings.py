"""A profile's `settings.json` and `.claude.json`: the account guide and sign-in."""

import json
from pathlib import Path

from claude_sync import fileio
from claude_sync.errors import ClaudeSyncError

LOGIN_METHOD = "claudeai"


def _load(file: Path) -> dict:
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ClaudeSyncError(f"{file}: cannot read: {error.strerror}") from error
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise ClaudeSyncError(f"{file}: invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ClaudeSyncError(f"{file}: expected a JSON object")
    return data


def read(profile_dir: Path) -> dict:
    return _load(Path(profile_dir) / "settings.json")


def apply_guide(profile_dir: Path, org_uuid: str) -> bool:
    """Set the login guide keys, keeping every other key; True when the file changed."""
    current = read(profile_dir)
    updated = {**current, "forceLoginMethod": LOGIN_METHOD, "forceLoginOrgUUID": [org_uuid]}
    if updated == current:
        return False
    text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    fileio.write_private(Path(profile_dir) / "settings.json", text)
    return True


def guide_of(settings: dict) -> str | None:
    """The organization the guide keys point to, None when absent or not the guide."""
    org = settings.get("forceLoginOrgUUID")
    if settings.get("forceLoginMethod") != LOGIN_METHOD:
        return None
    if isinstance(org, list) and len(org) == 1 and isinstance(org[0], str):
        return org[0]
    return None


def signed_in_org(profile_dir: Path) -> str | None:
    account = _load(Path(profile_dir) / ".claude.json").get("oauthAccount")
    if not isinstance(account, dict):
        return None
    org = account.get("organizationUuid")
    return org if isinstance(org, str) else None
