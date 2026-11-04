import stat

import pytest

from claude_sync import manifest
from claude_sync.errors import ClaudeSyncError
from claude_sync.manifest import (
    Account,
    Manifest,
    Marketplace,
    McpServer,
    Plugin,
    Skill,
    SkillSource,
    Tool,
)

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


def with_mcp() -> Manifest:
    return Manifest(
        (),
        (),
        Account(ORG),
        mcp=(
            McpServer(
                "api",
                "http",
                url="https://example.com/${PATH_PART:-mcp}",
                headers={"Authorization": "value:Bearer ${T}", "X-Key": "keychain:svc-x"},
            ),
            McpServer("events", "sse", url="https://example.com/sse"),
            McpServer(
                "tools",
                "stdio",
                command="npx",
                args=("-y", "pkg", "--home=${HOME}"),
                env={"TOKEN": "env:TOOLS_TOKEN", "KEY": "keychain:svc/acct", "MODE": "value:fast"},
            ),
        ),
    )


def test_mcp_tables_round_trip(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    manifest.save(file, with_mcp())
    loaded = manifest.load(file)
    assert loaded == with_mcp()
    assert list(loaded.mcp[2].env) == ["TOKEN", "KEY", "MODE"]


def test_render_puts_mcp_after_skills_sorted_by_name_before_account():
    text = manifest.render(
        Manifest(
            (),
            (),
            Account(ORG),
            with_skills().skill_sources,
            with_skills().skills,
            tuple(reversed(with_mcp().mcp)),
        )
    )
    assert text.index("[[skill]]") < text.index("[[mcp]]") < text.index("[account]")
    order = [text.index(f'[[mcp]]\nname = "{name}"') for name in ("api", "events", "tools")]
    assert order == sorted(order)


def test_manifest_without_mcp_tables_is_unchanged(tmp_path):
    assert manifest.load(write(tmp_path, "")).mcp == ()
    assert "mcp" not in manifest.render(full())


STDIO = '[[mcp]]\nname = "t"\ntransport = "stdio"\ncommand = "x"\n'
HTTP = '[[mcp]]\nname = "t"\ntransport = "http"\nurl = "https://x"\n'


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (STDIO + 'env = { TOKEN = "abc" }\n', "env:, keychain: or value:"),
        (HTTP + 'headers = { A = "abc" }\n', "env:, keychain: or value:"),
        (STDIO + 'env = { TOKEN = "env:1BAD" }\n', "env.TOKEN of 't'"),
        (STDIO + 'env = { TOKEN = "env:" }\n', "env.TOKEN of 't'"),
        (STDIO + 'env = { TOKEN = "value:" }\n', "env.TOKEN of 't'"),
        (HTTP + 'headers = { A = "value:" }\n', "headers.A of 't'"),
        (
            '[[mcp]]\nname = "t"\ntransport = "ws"\nurl = "https://x"\n',
            "invalid transport 'ws'",
        ),
        ('[[mcp]]\nname = "t"\ntransport = 3\ncommand = "x"\n', "invalid transport"),
        (STDIO + 'env = { TOKEN = "keychain:svc/a/b" }\n', "account must not contain /"),
        (STDIO + 'env = { TOKEN = "keychain:" }\n', "env.TOKEN of 't'"),
        (STDIO + 'env = { TOKEN = "keychain:/acct" }\n', "env.TOKEN of 't'"),
        (STDIO + 'env = { TOKEN = "keychain:svc/" }\n', "env.TOKEN of 't'"),
        (STDIO + "env = { TOKEN = 3 }\n", "env.TOKEN"),
        (STDIO + 'env = { "" = "env:A" }\n', "env key"),
        (STDIO + 'env = "x"\n', "env"),
        ('[[mcp]]\nname = "t"\ntransport = "ws"\ncommand = "x"\n', "ws"),
        ('[[mcp]]\nname = "-t"\ntransport = "stdio"\ncommand = "x"\n', "-t"),
        ('[[mcp]]\nname = "t"\ntransport = "stdio"\n', "command"),
        (HTTP.replace('url = "https://x"\n', ""), "url"),
        (STDIO + 'url = "https://x"\n', "url"),
        (STDIO + 'headers = { A = "env:A" }\n', "headers"),
        (HTTP + 'command = "x"\n', "command"),
        (HTTP + 'env = { A = "env:A" }\n', "env is not allowed on http server 't'"),
        (
            HTTP.replace('"http"', '"sse"') + 'env = { A = "env:A" }\n',
            "env is not allowed on sse server 't'",
        ),
        (HTTP + 'args = ["a"]\n', "args"),
        (STDIO + 'args = "a"\n', "args"),
        (STDIO + "args = [1]\n", "args"),
        (STDIO + "bogus = 1\n", "bogus"),
        (STDIO + STDIO, "duplicate"),
        ("mcp = 3\n", "mcp"),
    ],
)
def test_invalid_mcp_tables_name_file_and_problem(tmp_path, text, problem):
    file = write(tmp_path, text)
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert str(file) in str(error.value)
    assert problem in str(error.value)


def test_bare_value_error_does_not_echo_the_value(tmp_path):
    file = write(tmp_path, STDIO + 'env = { TOKEN = "s3cr3t-abc" }\n')
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert "s3cr3t-abc" not in str(error.value)
    assert "TOKEN" in str(error.value)


def test_minimal_mcp_servers_load_with_defaults(tmp_path):
    loaded = manifest.load(write(tmp_path, STDIO + HTTP.replace('"t"', '"u"')))
    assert loaded.mcp == (
        McpServer("t", "stdio", command="x"),
        McpServer("u", "http", url="https://x"),
    )
    assert loaded.mcp[0].args == () and loaded.mcp[0].env == {}


@pytest.mark.parametrize("bad", ["env:sk-LEAK 1", "keychain:leak/a/b", "keychain:/leakacct"])
def test_invalid_reference_errors_never_echo_the_text(tmp_path, bad):
    file = write(tmp_path, STDIO + f'env = {{ TOKEN = "{bad}" }}\n')
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    message = str(error.value)
    assert "env.TOKEN" in message
    assert "leak" not in message.lower().replace("unleak", "")


def test_invalid_reference_error_lists_the_allowed_kinds(tmp_path):
    file = write(tmp_path, STDIO + 'env = { TOKEN = "env:1BAD" }\n')
    with pytest.raises(manifest.ManifestError, match="env:<NAME>, keychain:.* or value:<text>"):
        manifest.load(file)


def test_empty_keys_are_named_per_table(tmp_path):
    for body, word in (
        ('env = { "" = "env:A" }\n', "env"),
        ('headers = { "" = "env:A" }\n', "headers"),
    ):
        text = STDIO.replace("command", "command") if word == "env" else HTTP
        with pytest.raises(manifest.ManifestError, match=f"empty {word} key"):
            manifest.load(write(tmp_path, text + body))


def with_tools() -> Manifest:
    return Manifest(
        (),
        (),
        None,
        tools=(
            Tool("gh", None, None, "brew:gh"),
            Tool("openspec", "1.12.0", None, "npm:@fission-ai/openspec"),
            Tool("rtk", "0.8", "rtk --version", "script:echo hi"),
        ),
    )


def test_tools_round_trip(tmp_path):
    file = tmp_path / manifest.MANIFEST_FILE
    manifest.save(file, with_tools())
    assert manifest.load(file) == with_tools()


def test_render_puts_tools_after_mcp_servers_sorted_by_name():
    text = manifest.render(
        Manifest(
            (),
            (),
            None,
            mcp=(McpServer("m", "http", url="https://x"),),
            tools=(Tool("zz", None, None, None), Tool("aa", "1", None, None)),
        )
    )
    assert text.index("[[mcp]]") < text.index('name = "aa"') < text.index('name = "zz"')
    assert text.count("[[tool]]") == 2
    assert "check" not in text and "install" not in text


def test_manifest_without_tool_tables_is_unchanged(tmp_path):
    loaded = manifest.load(write(tmp_path, ""))
    assert loaded.tools == ()
    assert "[[tool]]" not in manifest.render(full())


def test_minimal_tool_loads_with_defaults(tmp_path):
    loaded = manifest.load(write(tmp_path, '[[tool]]\nname = "jq"\n'))
    assert loaded.tools == (Tool("jq", None, None, None),)


def test_scoped_npm_package_is_accepted(tmp_path):
    loaded = manifest.load(write(tmp_path, '[[tool]]\nname = "x"\ninstall = "npm:@scope/pkg"\n'))
    assert loaded.tools[0].install == "npm:@scope/pkg"


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ('name = "bad name"\n', "invalid tool name"),
        ('name = ""\n', "tool name"),
        ('name = "a"\n[[tool]]\nname = "a"\n', "duplicate tool 'a'"),
        ('name = "a"\nversion = "x.y"\n', "version of 'a'"),
        ('name = "a"\nversion = "1"\n', "version of 'a'"),
        ('name = "a"\nversion = 2\n', "version of 'a'"),
        ('name = "a"\nversion = "1.2abc"\n', "version of 'a'"),
        ('name = "a"\nversion = "\\u0661.\\u0662"\n', "version of 'a'"),
        ('name = "a"\ninstall = "apt:jq"\n', "brew:, npm:, uv:, cargo: or script:"),
        ('name = "a"\ninstall = "jq"\n', "brew:, npm:, uv:, cargo: or script:"),
        ('name = "a"\ninstall = "brew:"\n', "empty"),
        ('name = "a"\ninstall = "script:"\n', "empty"),
        ('name = "a"\ninstall = "brew:two words"\n', "invalid"),
        ('name = "a"\ncheck = "b --version"\n', "first word"),
        ('name = "a"\ncheck = ""\n', "check of 'a'"),
        ('name = "a"\ncheck = "   "\n', "first word"),
        ('name = "a"\ninstall = "script: "\n', "empty"),
        ('name = "a"\ninstall = "script:echo\\u007f"\n', "control character"),
        ('name = "a"\ninstall = "script:echo\\rx"\n', "control character"),
        ('name = "a"\ncheck = "a \'unclosed"\n', "check of 'a'"),
        ('name = "a"\ninstall = "script:echo\\nrm x"\n', "single line"),
        ('name = "a"\ninstall = "script:echo\\u0007"\n', "control character"),
        ('name = "a"\ninstall = "brew:--force"\n', "invalid package"),
        ('name = "a"\nextra = 1\n', "unknown key 'extra'"),
    ],
)
def test_invalid_tool_tables_name_file_and_problem(tmp_path, body, problem):
    file = write(tmp_path, f"[[tool]]\n{body}")
    with pytest.raises(manifest.ManifestError) as error:
        manifest.load(file)
    assert str(file) in str(error.value)
    assert problem in str(error.value)


def test_tool_check_whose_first_word_is_the_name_is_accepted(tmp_path):
    loaded = manifest.load(write(tmp_path, '[[tool]]\nname = "a"\ncheck = "a -V --short"\n'))
    assert loaded.tools[0].check == "a -V --short"
