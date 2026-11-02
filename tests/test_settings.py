import json
import stat

import pytest

from claude_sync import settings
from claude_sync.errors import ClaudeSyncError

ORG = "00000000-0000-0000-0000-000000000000"


def test_guide_keys_are_written_into_a_missing_file(tmp_path):
    assert settings.apply_guide(tmp_path, ORG) is True
    file = tmp_path / "settings.json"
    assert json.loads(file.read_text()) == {
        "forceLoginMethod": "claudeai",
        "forceLoginOrgUUID": [ORG],
    }
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert file.read_text().startswith('{\n  "')
    assert [p.name for p in tmp_path.iterdir() if p.name != "home"] == ["settings.json"]


def test_existing_keys_are_kept(tmp_path):
    (tmp_path / "settings.json").write_text(
        json.dumps({"theme": "dark", "forceLoginOrgUUID": ["old"], "hooks": {"a": [1]}})
    )
    assert settings.apply_guide(tmp_path, ORG) is True
    assert settings.read(tmp_path) == {
        "theme": "dark",
        "hooks": {"a": [1]},
        "forceLoginMethod": "claudeai",
        "forceLoginOrgUUID": [ORG],
    }


def test_second_call_reports_no_change(tmp_path):
    settings.apply_guide(tmp_path, ORG)
    before = (tmp_path / "settings.json").read_text()
    assert settings.apply_guide(tmp_path, ORG) is False
    assert (tmp_path / "settings.json").read_text() == before


def test_invalid_json_raises_naming_the_file(tmp_path):
    file = tmp_path / "settings.json"
    file.write_text("{nope")
    for call in (lambda: settings.read(tmp_path), lambda: settings.apply_guide(tmp_path, ORG)):
        with pytest.raises(ClaudeSyncError) as error:
            call()
        assert str(file) in str(error.value)
    assert file.read_text() == "{nope"


def test_non_object_json_raises(tmp_path):
    (tmp_path / "settings.json").write_text("[1]")
    with pytest.raises(ClaudeSyncError, match="object"):
        settings.read(tmp_path)


def test_unreadable_settings_raise_naming_the_file(tmp_path):
    file = tmp_path / "settings.json"
    file.mkdir()
    with pytest.raises(ClaudeSyncError) as error:
        settings.read(tmp_path)
    assert str(file) in str(error.value)


def test_settings_file_ends_with_a_newline(tmp_path):
    settings.apply_guide(tmp_path, ORG)
    assert (tmp_path / "settings.json").read_text().endswith("}\n")


def test_non_ascii_values_stay_readable(tmp_path):
    (tmp_path / "settings.json").write_text('{"name": "caf\u00e9"}', encoding="utf-8")
    settings.apply_guide(tmp_path, ORG)
    assert "café" in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_apply_guide_creates_a_missing_profile_directory(tmp_path):
    settings.apply_guide(tmp_path / "new", ORG)
    assert settings.guide_of(settings.read(tmp_path / "new")) == ORG


def test_read_of_a_missing_file_is_empty(tmp_path):
    assert settings.read(tmp_path) == {}


def test_guide_of_returns_the_org_or_none():
    assert settings.guide_of({"forceLoginMethod": "claudeai", "forceLoginOrgUUID": [ORG]}) == ORG
    assert settings.guide_of({"forceLoginOrgUUID": [ORG]}) is None
    assert settings.guide_of({"forceLoginMethod": "claudeai"}) is None
    assert (
        settings.guide_of({"forceLoginMethod": "claudeai", "forceLoginOrgUUID": [ORG, "b"]}) is None
    )
    assert settings.guide_of({"forceLoginMethod": "console", "forceLoginOrgUUID": [ORG]}) is None
    assert settings.guide_of({"forceLoginMethod": "claudeai", "forceLoginOrgUUID": [1]}) is None
    assert settings.guide_of({}) is None


def test_signed_in_org_reads_the_oauth_account(tmp_path):
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"organizationUuid": ORG}}))
    assert settings.signed_in_org(tmp_path) == ORG


def test_signed_in_org_is_none_when_absent(tmp_path):
    assert settings.signed_in_org(tmp_path) is None
    (tmp_path / ".claude.json").write_text("{}")
    assert settings.signed_in_org(tmp_path) is None
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {}}))
    assert settings.signed_in_org(tmp_path) is None
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {"organizationUuid": 5}}))
    assert settings.signed_in_org(tmp_path) is None
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": "x"}))
    assert settings.signed_in_org(tmp_path) is None


def test_signed_in_org_with_invalid_json_raises(tmp_path):
    file = tmp_path / ".claude.json"
    file.write_text("{")
    with pytest.raises(ClaudeSyncError, match=str(file)):
        settings.signed_in_org(tmp_path)
