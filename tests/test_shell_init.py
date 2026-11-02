from claude_sync import paths
from claude_sync.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_other_shells_are_a_usage_error(capsys):
    code, out, err = run(capsys, "shell-init", "fish")
    assert (code, out) == (2, "")
    assert "argument SHELL: invalid choice: 'fish'" in err


def test_shell_code_has_no_json_form(capsys):
    code, out, err = run(capsys, "shell-init", "zsh", "--json")
    assert (code, out) == (2, "")
    assert "unrecognized arguments: --json" in err


def test_invalid_config_prints_nothing_on_stdout(capsys):
    paths.config_home().mkdir(parents=True)
    paths.config_file().write_text('default = "Bad!"\n')
    code, out, err = run(capsys, "shell-init", "zsh")
    assert (code, out) == (1, "")
    assert "invalid profile name 'Bad!'" in err


def test_snippet_registers_the_chpwd_hook(capsys):
    code, out, _ = run(capsys, "shell-init", "zsh")
    assert code == 0
    assert "add-zsh-hook chpwd _claude_sync_apply" in out
