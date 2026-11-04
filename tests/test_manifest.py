import stat

import pytest

from claude_sync import manifest
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import Account, Manifest, Marketplace, Plugin, Skill, SkillSource

COMMIT = "0123456789abcdef0123456789abcdef01234567"
ORG = "00000000-0000-0000-0000-000000000000"


def full() -> Manifest:
    return Manifest(
        marketplaces=(
            Marketplace("alpha", "github:owner/repo", "v1", COMMIT),
            Marketplace("beta", "git:https://example.com/x.git", None, None),
            Marketplace("gamma", "url:https://example.com/m.json", "main", None),
            Marketplace("local", "path:~/Dev/market", None, None),
        ),
        plugins=(
            Plugin("p@alpha", "1.2.3", True),
            Plugin("q@beta", "abc1234", False),
        ),
        account=Account(ORG),
    )


def write(tmp_path, text):
    file = tmp_path / manifest.MANIFEST_FILE
    file.write_text(text, encoding="utf-8")
    return file


def test_full_manifest_round_trips(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    manifest.save(file, full())
    assert manifest.load(file) == full()


def test_empty_manifest_round_trips(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    manifest.save(file, Manifest((), (), None))
    assert manifest.load(file) == Manifest((), (), None)


def test_render_sorts_marketplaces_by_name_then_plugins_by_id():
    text = manifest.render(
        Manifest(
            (
                Marketplace("b", "github:o/b", None, None),
                Marketplace("a", "github:o/a", None, None),
            ),
            (Plugin("z@a", "1", True), Plugin("y@b", "1", True)),
            None,
        )
    )
    assert text.index('name = "a"') < text.index('name = "b"')
    assert text.index('"y@b"') < text.index('"z@a"')


def test_save_writes_mode_600_and_leaves_no_temp_file(tmp_path):
    directory = tmp_path / "profile"
    directory.mkdir()
    file = directory / manifest.MANIFEST_FILE
    manifest.save(file, full())
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert [p.name for p in directory.iterdir()] == [manifest.MANIFEST_FILE]


def test_save_replaces_an_existing_file(tmp_path):
    file = write(tmp_path, "garbage")
    manifest.save(file, Manifest((), (), None))
    assert manifest.load(file) == Manifest((), (), None)


def market(**fields):
    table = {"name": "m", "source": "github:o/r", **fields}
    return "[[marketplace]]\n" + "".join(f'{k} = "{v}"\n' for k, v in table.items())


def test_commit_must_be_40_lowercase_hex(tmp_path):
    for bad in (COMMIT[:39], COMMIT.upper(), "z" * 40):
        file = write(tmp_path, market(commit=bad))
        with pytest.raises(manifest.ManifestError) as error:
            manifest.load(file)
        assert str(file) in str(error.value)
        assert "commit" in str(error.value)


def test_ref_and_commit_are_refused_on_path_sources(tmp_path):
    for extra in ({"ref": "main"}, {"commit": COMMIT}):
        file = write(tmp_path, market(source="path:/x", **extra))
        with pytest.raises(manifest.ManifestError, match="path"):
            manifest.load(file)


@pytest.mark.parametrize(
    "source", ["ftp:x", "owner/repo", "github:owner", "github:a/b/c", "git:", "url:", "path:"]
)
def test_invalid_sources_are_refused(tmp_path, source):
    file = write(tmp_path, market(source=source))
    with pytest.raises(manifest.ManifestError, match="source"):
        manifest.load(file)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("surprise = 1\n", "surprise"),
        (market() + 'extra = "x"\n', "extra"),
        (market() + market(), "duplicate"),
        (
            market() + '[[plugin]]\nid = "a@m"\nversion = "1"\nenabled = true\n'
            '[[plugin]]\nid = "a@m"\nversion = "1"\nenabled = true\n',
            "duplicate",
        ),
        (market() + '[[plugin]]\nid = "a@nope"\nversion = "1"\nenabled = true\n', "nope"),
        ('[account]\norg_uuid = "not-a-uuid"\n', "org_uuid"),
        ('[account]\norg_uuid = "x"\nother = 1\n', "other"),
        ("not toml [", "TOML"),
        (market(ref=""), "ref"),
        (market() + '[[plugin]]\nid = "a@m"\nversion = ""\nenabled = true\n', "version"),
        (market() + '[[plugin]]\nid = "@m"\nversion = "1"\nenabled = true\n', "@m"),
        (market() + '[[plugin]]\nid = "p@"\nversion = "1"\nenabled = true\n', "p@"),
        ("marketplace = [1]\n", "array of tables"),
        ("plugin = [1]\n", "array of tables"),
        (market() + '[[plugin]]\nid = "nomarket"\nversion = "1"\nenabled = true\n', "nomarket"),
        (market() + '[[plugin]]\nid = "a@m"\nversion = "1"\nenabled = "yes"\n', "enabled"),
        (market() + '[[plugin]]\nid = "a@m"\nenabled = true\n', "version"),
        (market() + '[[plugin]]\nid = "a@m"\nversion = "1"\nenabled = true\nzzz = 1\n', "zzz"),
        ('marketplace = "x"\n', "marketplace"),
        ('plugin = "x"\n', "plugin"),
        ('account = "x"\n', "account"),
        ('[[marketplace]]\nname = "m"\n', "source"),
        ('[[marketplace]]\nname = "Bad Name"\nsource = "github:o/r"\n', "name"),
    ],
)
def test_invalid_manifests_raise_naming_file_and_problem(tmp_path, text, problem):
    file = write(tmp_path, text)
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert isinstance(error.value, ClaudeSyncError)
    assert str(file) in str(error.value)
    assert problem in str(error.value)


def test_non_utf8_file_raises_naming_the_file(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    file.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert str(file) in str(error.value)


def test_unreadable_file_raises_manifest_error(tmp_path):
    with pytest.raises(manifest.ManifestError, match="cannot read"):
        manifest.load(tmp_path / "missing.toml")


def test_source_spec_per_type(tmp_path, isolated_environment):
    def spec(source, ref=None):
        return manifest.source_spec(Marketplace("m", source, ref, None))

    assert spec("github:owner/repo") == "owner/repo"
    assert spec("github:owner/repo", "v1") == "owner/repo#v1"
    assert spec("git:https://example.com/x.git") == "https://example.com/x.git"
    assert spec("git:https://example.com/x.git", "dev") == "https://example.com/x.git#dev"
    assert spec("url:https://example.com/m.json", "main") == "https://example.com/m.json#main"
    assert spec("url:https://example.com/m.json") == "https://example.com/m.json"
    assert spec("path:/abs/dir") == "/abs/dir"
    expanded = spec("path:~/Dev/market")
    assert expanded == str((isolated_environment / "Dev" / "market").resolve())


TREE = "fedcba9876543210fedcba9876543210fedcba98"


def with_skills() -> Manifest:
    return Manifest(
        marketplaces=(),
        plugins=(),
        account=None,
        skill_sources=(
            SkillSource("local", "git:https://example.com/x.git", None, None),
            SkillSource("tools", "github:acme/skills", "main", COMMIT),
        ),
        skills=(
            Skill("grill@tools", "skills/grill", None),
            Skill("tdd@tools", "skills/engineering/tdd", TREE),
        ),
    )


def test_skills_round_trip(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    manifest.save(file, with_skills())
    assert manifest.load(file) == with_skills()


def test_manifest_without_skill_tables_is_unchanged(tmp_path):
    file = write(tmp_path, '[[marketplace]]\nname = "a"\nsource = "github:o/a"\n')
    loaded = manifest.load(file)
    assert loaded.skill_sources == () and loaded.skills == ()
    assert manifest.render(loaded) == '[[marketplace]]\nname = "a"\nsource = "github:o/a"\n'


def test_render_puts_skills_after_plugins_sorted():
    ordered = with_skills()
    text = manifest.render(
        Manifest(
            (),
            (),
            None,
            tuple(reversed(ordered.skill_sources)),
            tuple(reversed(ordered.skills)),
        )
    )
    assert text.index('name = "local"') < text.index('name = "tools"')
    assert text.index('"grill@tools"') < text.index('"tdd@tools"')
    assert text.index("[[skill_source]]") < text.index("[[skill]]")
    full_text = manifest.render(full())
    assert "skill" not in full_text


def test_render_orders_plugins_before_skill_tables():
    text = manifest.render(
        Manifest(
            (), (Plugin("p@a", "1", True),), None, with_skills().skill_sources, with_skills().skills
        )
    )
    assert text.index("[[plugin]]") < text.index("[[skill_source]]")


SRC = '[[skill_source]]\nname = "tools"\nsource = "github:acme/skills"\n'


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('[[skill_source]]\nname = "t"\nsource = "url:https://x"\n', "url:https://x"),
        ('[[skill_source]]\nname = "t"\nsource = "github:nope"\n', "github:nope"),
        ('[[skill_source]]\nname = "t"\nsource = "git:"\n', "git:"),
        ('[[skill_source]]\nname = "-t"\nsource = "git:x"\n', "-t"),
        ('[[skill_source]]\nname = "t"\nsource = "git:x"\ncommit = "abc"\n', "commit"),
        ('[[skill_source]]\nname = "t"\nsource = "git:x"\nref = ""\n', "ref"),
        ('[[skill_source]]\nname = "t"\nsource = "git:x"\nbogus = 1\n', "bogus"),
        ('[[skill_source]]\nname = "t"\n', "source"),
        (
            '[[skill_source]]\nname = "t"\nsource = "git:x"\n'
            '[[skill_source]]\nname = "t"\nsource = "git:y"\n',
            "duplicate",
        ),
        (SRC + '[[skill]]\nid = "tdd"\npath = "a"\n', "tdd"),
        (SRC + '[[skill]]\nid = "TDD@tools"\npath = "a"\n', "TDD@tools"),
        (SRC + '[[skill]]\nid = "tdd@other"\npath = "a"\n', "other"),
        (SRC + '[[skill]]\nid = "tdd@tools"\npath = "/abs"\n', "/abs"),
        (SRC + '[[skill]]\nid = "tdd@tools"\npath = "a/../b"\n', "a/../b"),
        (SRC + '[[skill]]\nid = "tdd@tools"\npath = ""\n', "path"),
        (SRC + '[[skill]]\nid = "tdd@tools"\npath = "a"\ntree = "xyz"\n', "tree"),
        (SRC + '[[skill]]\nid = "tdd@tools"\npath = "a"\nbogus = 1\n', "bogus"),
        (SRC + '[[skill]]\nid = "tdd@tools"\n', "path"),
        (
            SRC
            + '[[skill]]\nid = "tdd@tools"\npath = "a"\n[[skill]]\nid = "tdd@tools"\npath = "b"\n',
            "duplicate",
        ),
    ],
)
def test_invalid_skill_tables_name_file_and_problem(tmp_path, text, problem):
    file = write(tmp_path, text)
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert str(file) in str(error.value)
    assert problem in str(error.value)


def test_valid_skill_without_optional_fields_loads(tmp_path):
    file = write(tmp_path, SRC + '[[skill]]\nid = "tdd@tools"\npath = "a/b"\n')
    loaded = manifest.load(file)
    assert loaded.skills == (Skill("tdd@tools", "a/b", None),)
    assert loaded.skill_sources == (SkillSource("tools", "github:acme/skills", None, None),)


def test_skill_id_without_at_has_a_dedicated_error(tmp_path):
    file = write(tmp_path, SRC + '[[skill]]\nid = "tdd"\npath = "a"\n')
    with pytest.raises(manifest.ManifestError, match="skill id .* must be <skill>@<source name>"):
        manifest.load(file)


@pytest.mark.parametrize("path", [".", "a/./b", "./a", "a//b", "a/b/", "a/.."])
def test_odd_skill_paths_are_rejected(tmp_path, path):
    file = write(tmp_path, SRC + f'[[skill]]\nid = "tdd@tools"\npath = "{path}"\n')
    with pytest.raises(manifest.ManifestError, match="path of"):
        manifest.load(file)
