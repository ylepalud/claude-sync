import stat

import pytest

from claude_sync import config, paths
from claude_sync.config import Config, ConfigError, Match
from claude_sync.errors import ClaudeSyncError


def write(text: str):
    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_absent_file_gives_default_configuration():
    assert config.load() == Config("perso", ())


def test_valid_file_round_trips():
    original = Config("perso", (Match("~/Dev/work", "work"), Match("/opt/x", "side-1")))
    config.save(original)
    assert config.load() == original


def test_path_with_quote_and_backslash_round_trips():
    original = Config("perso", (Match('/tmp/a"b\\c', "work"),))
    config.save(original)
    assert config.load() == original


def test_save_uses_private_modes():
    config.save(Config("perso", ()))
    assert stat.S_IMODE(paths.config_home().stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.config_file().stat().st_mode) == 0o600


def test_save_replaces_existing_file_and_leaves_no_temp_files():
    config.save(Config("perso", ()))
    config.save(Config("work", ()))
    assert config.load().default == "work"
    assert [p.name for p in paths.config_home().iterdir()] == ["config.toml"]


@pytest.mark.parametrize(
    "text",
    [
        'default = "perso"\nbogus = 1\n',
        'default = "perso"\n[[match]]\npath = "~/x"\n',
        'default = "perso"\n[[match]]\nprofile = "w"\n',
        "default = \n",
        '[[match]]\npath = "~/x"\nprofile = "w"\n',
        'default = "Work!"\n',
        'default = "-x"\n',
        'default = "ab!"\n',
        "default = 1\n",
        'default = "perso"\n[[match]]\npath = "~/x"\nprofile = "Work!"\n',
        'default = "perso"\n[[match]]\npath = "~/x"\nprofile = "w"\nextra = 1\n',
    ],
)
def test_invalid_file_raises_config_error_naming_the_file(text):
    path = write(text)
    with pytest.raises(ConfigError) as excinfo:
        config.load()
    assert str(path) in str(excinfo.value)
    assert isinstance(excinfo.value, ClaudeSyncError)


def test_profile_name_pattern():
    assert config.PROFILE_NAME.fullmatch("work-2")
    assert not config.PROFILE_NAME.fullmatch("-work")
    assert not config.PROFILE_NAME.fullmatch("Work")


def test_path_with_control_characters_round_trips():
    original = Config("perso", (Match("/tmp/a\tb\nc\x7f", "work"),))
    config.save(original)
    assert config.load() == original
