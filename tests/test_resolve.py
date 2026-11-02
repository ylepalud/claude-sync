import pytest

from claude_sync import paths
from claude_sync.config import Config, Match
from claude_sync.errors import ClaudeSyncError
from claude_sync.resolve import resolve

CONFIG = Config("perso", (Match("~/Dev/work", "work"), Match("~/Dev/work/oss", "perso")))


@pytest.fixture
def home(isolated_environment):
    for name in ("Dev/work/oss/lib", "Dev/work/api", "Dev/workshop"):
        (isolated_environment / name).mkdir(parents=True)
    return isolated_environment


def test_no_config_gives_default(home):
    result = resolve(home, Config("perso", ()), None)
    assert (result.profile, result.source, result.match) == ("perso", "default", None)


def test_longest_prefix_wins(home):
    deep = resolve(home / "Dev/work/oss/lib", CONFIG, None)
    assert (deep.profile, deep.source, deep.match) == ("perso", "match", "~/Dev/work/oss")
    assert resolve(home / "Dev/work/api", CONFIG, None).profile == "work"
    assert resolve(home / "Dev/work", CONFIG, None).profile == "work"


def test_longest_prefix_wins_regardless_of_config_order(home):
    reordered = Config("perso", tuple(reversed(CONFIG.matches)))
    assert resolve(home / "Dev/work/oss/lib", reordered, None).profile == "perso"


def test_component_boundary(home):
    result = resolve(home / "Dev/workshop", CONFIG, None)
    assert (result.profile, result.source) == ("perso", "default")


def test_symlinked_directory_resolves_to_target(home):
    (home / "w").symlink_to(home / "Dev/work")
    assert resolve(home / "w/api", CONFIG, None).profile == "work"


def test_override_wins(home):
    result = resolve(home / "Dev/work/api", CONFIG, "other")
    assert (result.profile, result.source, result.match) == ("other", "override", None)


def test_invalid_override_raises(home):
    with pytest.raises(ClaudeSyncError, match="Work!"):
        resolve(home, CONFIG, "Work!")


def test_config_dir_and_initialized(home):
    before = resolve(home / "Dev/work/api", CONFIG, None)
    assert before.config_dir == paths.profile_dir("work")
    assert before.initialized is False
    paths.profile_dir("work").mkdir(parents=True)
    assert resolve(home / "Dev/work/api", CONFIG, None).initialized is True
    assert resolve(home, CONFIG, None).initialized is False


def test_override_with_a_valid_prefix_but_invalid_tail_raises(home):
    with pytest.raises(ClaudeSyncError):
        resolve(home, CONFIG, "ab!")


def test_wrong_case_directory_resolves_like_the_on_disk_one(home, case_insensitive_fs):
    result = resolve(home / "dev" / "work" / "api", CONFIG, None)
    assert (result.profile, result.source) == ("work", "match")


def test_wrong_case_mapping_applies(home, case_insensitive_fs):
    config = Config("perso", (Match("~/dev/work", "work"),))
    assert resolve(home / "Dev" / "work" / "api", config, None).profile == "work"
