"""End to end against the real `claude` CLI and the network; opt in with CLAUDE_SYNC_E2E=1.

HOME is the temporary directory of the isolation fixture, so the real
~/.claude is never read or written; the profile is created inside it.
"""

import json
import os

import pytest

from claude_sync import manifest, paths
from claude_sync.claude_cli import ClaudeCli
from claude_sync.cli import main

pytestmark = pytest.mark.skipif(
    os.environ.get("CLAUDE_SYNC_E2E") != "1", reason="set CLAUDE_SYNC_E2E=1 to run"
)

MARKETPLACE = "claude-plugins-official"
PLUGIN = f"commit-commands@{MARKETPLACE}"


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_apply_then_status_on_a_new_profile(capsys):
    assert run(capsys, "profile", "create", "e2e")[0] == 0
    directory = paths.profile_dir("e2e")
    declared = manifest.Manifest(
        (
            manifest.Marketplace(
                MARKETPLACE, "github:anthropics/claude-plugins-official", None, None
            ),
        ),
        (manifest.Plugin(PLUGIN, "0", True),),
        None,
    )
    manifest.save(directory / manifest.MANIFEST_FILE, declared)

    code, out, err = run(capsys, "apply", "--profile", "e2e")
    # The placeholder version differs from the one served today: reported as drift.
    assert code == 4, (out, err)

    code, out, err = run(capsys, "status", "--profile", "e2e", "--json")
    kinds = {(d["kind"], d["subject"]) for d in json.loads(out)["differences"]}
    assert not {k for k, _ in kinds} & {"missing", "unlisted", "source"}, kinds

    served = {p.id: p.version for p in ClaudeCli(directory).plugins()}
    assert PLUGIN in served
    manifest.save(
        directory / manifest.MANIFEST_FILE,
        manifest.Manifest(
            declared.marketplaces, (manifest.Plugin(PLUGIN, served[PLUGIN], True),), None
        ),
    )

    code, out, err = run(capsys, "apply", "--profile", "e2e", "--dry-run")
    assert (code, out) == (0, ""), (code, out, err)
    assert run(capsys, "apply", "--profile", "e2e")[0] == 0
    code, out, err = run(capsys, "status", "--profile", "e2e")
    assert code == 0, (out, err)
