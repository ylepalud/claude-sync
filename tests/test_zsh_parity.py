"""The zsh snippet, evaluated by a real `zsh -f` (never the maintainer's ~/.zshrc)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claude_sync import config, paths, zsh
from claude_sync.config import Config, Match
from claude_sync.resolve import resolve

ZSH = shutil.which("zsh")
if ZSH is None:
    if os.environ.get("CI"):
        pytest.fail("zsh is required in CI", pytrace=False)
    pytest.skip("zsh is not installed", allow_module_level=True)


def evaluate(tmp_path, script, env=None, cwd=None, before=""):
    """Run `before`, source the snippet of the saved config in `zsh -f`, run `script`."""
    snippet = tmp_path / "snippet.zsh"
    snippet.write_text(zsh.render(config.load()))
    # claude-sync of this environment resolves, nothing else from the caller's PATH.
    base = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    base.update({k: os.environ[k] for k in ("HOME", "XDG_CONFIG_HOME") if k in os.environ})
    base.update(env or {})
    result = subprocess.run(
        [ZSH, "-f", "-c", f'{before}\nsource "$1"\n{script}', "zsh", str(snippet)],
        env=base,
        cwd=cwd or tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def test_single_quotes_in_paths_are_quoted(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "it's config"))
    config.save(Config("perso", (Match(str(tmp_path / "o'brien"), "work"),)))
    result = evaluate(
        tmp_path, "print -r -- $_claude_sync_root; print -r -- $_claude_sync_matches[1]"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(paths.profiles_root()),
        str(paths.normalize(tmp_path / "o'brien")),
    ]


def test_resolve_agrees_with_python(tmp_path):
    dev = tmp_path / "Dev"
    for d in ("work/sub", "work/oss/deep", "workshop", "o'brien/x", "real/x"):
        (dev / d).mkdir(parents=True)
    (dev / "alias").symlink_to(dev / "real")
    (dev / "to-oss").symlink_to(dev / "work/oss")
    cfg = Config(
        "home",
        (
            Match(str(dev / "work"), "work"),
            Match(str(dev / "work/oss"), "oss"),
            Match(str(dev / "o'brien"), "quote"),
            Match(str(dev / "alias"), "linked"),
        ),
    )
    config.save(cfg)
    dirs = [
        tmp_path,
        dev / "work",
        dev / "work/sub",
        dev / "work/oss",
        dev / "work/oss/deep",
        dev / "workshop",
        dev / "o'brien",
        dev / "o'brien/x",
        dev / "alias",
        dev / "real/x",
        dev / "to-oss",
        dev / "missing/dir",
    ]
    script = "".join(
        f"_claude_sync_resolve {zsh.quote(str(d))}; print -r -- $REPLY\n" for d in dirs
    )
    result = evaluate(tmp_path, script)
    assert result.returncode == 0, result.stderr
    expected = [resolve(d, cfg, None).profile for d in dirs]
    assert expected == [
        "home", "work", "work", "oss", "oss", "home",
        "quote", "quote", "linked", "linked", "oss", "home",
    ]  # fmt: skip
    assert result.stdout.splitlines() == expected


def test_cd_updates_the_profile(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(
        tmp_path, "print -r -- $CLAUDE_SYNC_PROFILE; cd work; printenv CLAUDE_SYNC_PROFILE"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["perso", "work"]


def test_config_dir_is_exported_only_for_an_initialized_profile(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    paths.profile_dir("work").mkdir(parents=True)
    result = evaluate(
        tmp_path, "print -r -- ${CLAUDE_CONFIG_DIR-unset}; cd work; printenv CLAUDE_CONFIG_DIR"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["unset", str(paths.profile_dir("work"))]


def test_user_config_dir_is_kept_and_restored(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    paths.profile_dir("work").mkdir(parents=True)
    result = evaluate(
        tmp_path,
        "printenv CLAUDE_CONFIG_DIR; cd work; printenv CLAUDE_CONFIG_DIR; cd ..\n"
        "printenv CLAUDE_CONFIG_DIR; printenv CLAUDE_SYNC_USER_CONFIG_DIR",
        env={"CLAUDE_CONFIG_DIR": "/user/claude"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "/user/claude",
        str(paths.profile_dir("work")),
        "/user/claude",
        "/user/claude",
    ]


def test_child_shell_unsets_an_inherited_owned_config_dir(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    paths.profile_dir("work").mkdir(parents=True)
    result = evaluate(
        tmp_path,
        "cd ..; print -r -- ${CLAUDE_CONFIG_DIR-unset} ${CLAUDE_SYNC_USER_CONFIG_DIR-unset}",
        env={"CLAUDE_CONFIG_DIR": str(paths.profile_dir("work"))},
        cwd=tmp_path / "work",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["unset unset"]


def test_which_agrees_with_an_override(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(tmp_path, "claude-sync-use perso; claude-sync which", cwd=tmp_path / "work")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["perso"]


def test_an_invalid_inherited_override_is_ignored_with_one_warning(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(
        tmp_path,
        "print -r -- $CLAUDE_SYNC_PROFILE; cd work; print -r -- $CLAUDE_SYNC_PROFILE",
        env={"CLAUDE_SYNC_OVERRIDE": "Bad!"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["perso", "work"]
    assert result.stderr.splitlines() == [
        "claude-sync: ignoring invalid CLAUDE_SYNC_OVERRIDE 'Bad!' (expected [a-z0-9][a-z0-9-]*)"
    ]


def test_reload_applies_a_new_mapping_and_keeps_one_hook(tmp_path):
    (tmp_path / "work").mkdir()
    result = evaluate(
        tmp_path,
        "claude-sync map work work 2>/dev/null; cd work; print -r -- $CLAUDE_SYNC_PROFILE\n"
        "claude-sync-reload; print -r -- $CLAUDE_SYNC_PROFILE\n"
        "print -r -- ${#${(M)chpwd_functions:#_claude_sync_apply}}",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["perso", "work", "1"]


def test_prompt_segment_comes_before_the_existing_rprompt(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    paths.profile_dir("perso").mkdir(parents=True)
    result = evaluate(
        tmp_path,
        "cd work; print -r -- $RPROMPT; cd ..; print -r -- $RPROMPT",
        env={"RPROMPT": "%T"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["claude:work? %T", "claude:perso %T"]


def test_prompt_opt_out_leaves_rprompt_untouched(tmp_path):
    result = evaluate(
        tmp_path, "print -r -- $RPROMPT", env={"RPROMPT": "%T", "CLAUDE_SYNC_PROMPT": "0"}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["%T"]


def test_use_overrides_until_auto(tmp_path):
    (tmp_path / "work/sub").mkdir(parents=True)
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(
        tmp_path,
        "claude-sync-use perso; print -r -- $CLAUDE_SYNC_PROFILE $RPROMPT\n"
        "cd sub; print -r -- $CLAUDE_SYNC_PROFILE\n"
        "claude-sync-use --auto; print -r -- $CLAUDE_SYNC_PROFILE ${CLAUDE_SYNC_OVERRIDE-unset}",
        cwd=tmp_path / "work",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["perso claude:perso?", "perso", "work unset"]


def test_use_rejects_an_invalid_name_and_changes_nothing(tmp_path):
    result = evaluate(
        tmp_path,
        "claude-sync-use perso; before=$(typeset -p CLAUDE_SYNC_OVERRIDE CLAUDE_SYNC_PROFILE)\n"
        "claude-sync-use 'Bad!'; print -r -- $?\n"
        '[[ $before == "$(typeset -p CLAUDE_SYNC_OVERRIDE CLAUDE_SYNC_PROFILE)" ]] && print same',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1", "same"]
    assert "invalid profile name 'Bad!'" in result.stderr


def test_evaluating_twice_registers_one_hook_and_one_segment(tmp_path):
    result = evaluate(
        tmp_path,
        'source "$1"\n'
        "print -r -- ${#${(M)chpwd_functions:#_claude_sync_apply}}; print -r -- $RPROMPT",
        env={"RPROMPT": "%T"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1", "claude:perso? %T"]


def test_a_saved_user_config_dir_is_not_overwritten(tmp_path):
    result = evaluate(
        tmp_path,
        "printenv CLAUDE_SYNC_USER_CONFIG_DIR; printenv CLAUDE_CONFIG_DIR",
        env={"CLAUDE_SYNC_USER_CONFIG_DIR": "/user/saved", "CLAUDE_CONFIG_DIR": "/user/other"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["/user/saved", "/user/saved"]


def test_a_user_config_dir_exported_after_load_is_kept(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(
        tmp_path, "export CLAUDE_CONFIG_DIR=/user/later; cd work; printenv CLAUDE_CONFIG_DIR"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["/user/later"]


@pytest.mark.parametrize("name", ["-x", "a!"])
def test_use_rejects_names_outside_the_profile_rule(tmp_path, name):
    assert not config.PROFILE_NAME.fullmatch(name)
    result = evaluate(
        tmp_path,
        f"claude-sync-use {zsh.quote(name)}; print -r -- $? ${{CLAUDE_SYNC_OVERRIDE-unset}}",
    )
    assert result.stdout.splitlines() == ["1 unset"]


@pytest.mark.parametrize("option", ["ksh_arrays", "no_unset", "no_case_match"])
def test_caller_options_do_not_change_the_snippet(tmp_path, option):
    (tmp_path / "work/sub").mkdir(parents=True)
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(
        tmp_path,
        "cd work/sub; print -r -- $CLAUDE_SYNC_PROFILE\n"
        "claude-sync-use; print -r -- $?\n"
        "claude-sync-use Bad; print -r -- $? ${CLAUDE_SYNC_OVERRIDE-unset}",
        before=f"setopt {option}",
    )
    assert result.stdout.splitlines() == ["work", "1", "1 unset"]
    assert result.stderr.splitlines() == [
        "claude-sync-use: invalid profile name '' (expected [a-z0-9][a-z0-9-]*)",
        "claude-sync-use: invalid profile name 'Bad' (expected [a-z0-9][a-z0-9-]*)",
    ]


@pytest.mark.parametrize("option", ["ksh_arrays", "no_unset", "no_case_match"])
def test_caller_options_do_not_let_an_invalid_inherited_override_through(tmp_path, option):
    config.save(Config("perso", ()))
    result = evaluate(
        tmp_path,
        "print -r -- $CLAUDE_SYNC_PROFILE",
        env={"CLAUDE_SYNC_OVERRIDE": "Bad"},
        before=f"setopt {option}",
    )
    assert result.stdout.splitlines() == ["perso"]
    assert "ignoring invalid CLAUDE_SYNC_OVERRIDE 'Bad'" in result.stderr


def test_reload_fails_and_changes_nothing_when_the_config_is_invalid(tmp_path):
    (tmp_path / "work").mkdir()
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    file = zsh.quote(str(paths.config_file()))
    result = evaluate(
        tmp_path,
        f"print 'default = \"Bad!\"' > {file}\n"
        "claude-sync-reload; print -r -- $?\n"
        "cd work; print -r -- $CLAUDE_SYNC_PROFILE $_claude_sync_default",
    )
    assert result.stdout.splitlines() == ["1", "work perso"]
    assert "invalid profile name 'Bad!'" in result.stderr


def _utf8_locale():
    available = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False)
    # glibc lists normalized names (C.utf8), macOS the canonical ones (en_US.UTF-8).
    names = {n.lower().replace("-", "") for n in available.stdout.split()}
    return next(
        (n for n in ("en_US.UTF-8", "C.UTF-8") if n.lower().replace("-", "") in names), None
    )


def test_names_are_checked_with_ascii_semantics_under_a_utf8_locale(tmp_path):
    locale = _utf8_locale()
    if locale is None:
        pytest.skip("no UTF-8 locale (en_US.UTF-8 or C.UTF-8) is available")
    result = evaluate(
        tmp_path,
        "claude-sync-use 'é'; print -r -- $?\n"
        "claude-sync-use work; print -r -- $? $CLAUDE_SYNC_OVERRIDE\n"
        "print -r -- $LC_ALL",
        env={"LC_ALL": locale},
    )
    assert result.stdout.splitlines() == ["1", "0 work", locale]


def test_table_uses_the_on_disk_spelling(tmp_path, case_insensitive_fs):
    (tmp_path / "Work" / "sub").mkdir(parents=True)
    config.save(Config("perso", (Match(str(tmp_path / "work"), "work"),)))
    result = evaluate(tmp_path, "print -r -- $_claude_sync_matches[1]")
    assert result.stdout.splitlines() == [str(paths.normalize(tmp_path / "Work"))]
