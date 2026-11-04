import pytest

from claude_sync import secrets
from claude_sync.errors import ClaudeSyncError


def test_env_reference_becomes_a_placeholder():
    assert secrets.resolve("env:SERVICE_TOKEN") == "${SERVICE_TOKEN}"


def test_value_reference_is_its_text():
    assert secrets.resolve("value:Bearer ${T}") == "Bearer ${T}"
    assert secrets.resolve("value:a:b") == "a:b"


def test_keychain_reference_reads_the_service(fake_keychain):
    fake_keychain.set("service-x", "s3cr3t")
    assert secrets.resolve("keychain:service-x") == "s3cr3t"
    assert fake_keychain.calls() == [["find-generic-password", "-s", "service-x", "-w"]]


def test_keychain_reference_with_account(fake_keychain):
    fake_keychain.set("service-x", "no", account=None)
    fake_keychain.set("service-x", "yes", account="me")
    assert secrets.resolve("keychain:service-x/me") == "yes"
    assert fake_keychain.calls() == [["find-generic-password", "-s", "service-x", "-a", "me", "-w"]]


def test_keychain_value_strips_only_the_final_newline(fake_keychain):
    fake_keychain.set("multi", "line one\nline two ")
    assert secrets.keychain_value("multi", None) == "line one\nline two "


def test_missing_keychain_item_names_the_reference_only(fake_keychain):
    with pytest.raises(ClaudeSyncError) as error:
        secrets.resolve("keychain:service-x/me")
    message = str(error.value)
    assert "keychain:service-x/me" in message
    assert "not found" in message
    assert "SecKeychain" not in message


def test_other_failure_names_the_reference_without_tool_output(fake_keychain, monkeypatch):
    fake_keychain.set("service-x", "s3cr3t")
    monkeypatch.setenv("FAKE_SECURITY_EXIT", "51")
    with pytest.raises(ClaudeSyncError) as error:
        secrets.resolve("keychain:service-x")
    message = str(error.value)
    assert "keychain:service-x" in message
    assert "51" in message
    assert "s3cr3t" not in message


def test_missing_security_tool_is_an_error(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(ClaudeSyncError, match="keychain:service-x"):
        secrets.resolve("keychain:service-x")


@pytest.mark.parametrize("reference", ["TOKEN", "plain:x", "env:", "keychain:"])
def test_unknown_reference_kind_is_an_error(reference):
    with pytest.raises(ClaudeSyncError, match="reference"):
        secrets.resolve(reference)


def test_empty_value_reference_is_an_error():
    with pytest.raises(ClaudeSyncError, match="value:"):
        secrets.resolve("value:")


def test_keychain_value_keeps_carriage_returns(fake_keychain):
    fake_keychain.set("crlf", "a\r\nb\rc\r\n")
    assert secrets.keychain_value("crlf", None) == "a\r\nb\rc\r\n"


def test_keychain_value_strips_a_single_final_newline(fake_keychain):
    fake_keychain.set("nl", "x\n")
    assert secrets.keychain_value("nl", None) == "x\n"  # the tool added one more


def test_non_utf8_output_is_an_error_naming_the_reference(fake_keychain, monkeypatch):
    fake_keychain.set("bin", "x")
    monkeypatch.setenv("FAKE_SECURITY_RAW", "ff fe 41")
    with pytest.raises(ClaudeSyncError) as error:
        secrets.resolve("keychain:bin")
    assert "keychain:bin" in str(error.value)
    assert "UTF-8" in str(error.value)
    assert "ff" not in str(error.value).lower().replace("utf-8", "")


def test_account_with_slash_is_refused_with_a_reason():
    with pytest.raises(ClaudeSyncError, match="account must not contain /"):
        secrets.resolve("keychain:svc/a/b")
