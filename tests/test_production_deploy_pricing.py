"""Execute the real production checkout scripts against disposable local Git repos."""

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRICE = "data/price.json"
ADMIN_PRICE = b'{\n  "seedance25_quality_costs": {"480p": 5, "720p": 7, "1080p": 13},\n  "admin_note": "keep exact whitespace too"\n}\n'
DEPLOY_PATHS = [
    ("deploy-production-reliable.yml", 0),
    ("deploy-production.yml", 0),
    ("deploy-production.yml", 1),
]


def _checkout_script(workflow_name, index):
    source = (ROOT / ".github/workflows" / workflow_name).read_text()
    scripts = re.findall(
        r"^          set -Eeuo pipefail\n          PROJECT_DIR=.*?"
        r"(?=^          (?:run_root\(\) \{|bash scripts/deploy_backend_docker.sh deploy))",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert len(scripts) == (1 if "reliable" in workflow_name else 2)
    # Only redirect the host-wide lock. Git, backup, validation, reset and restore
    # execute unchanged; Docker/deployment is outside this filesystem seam.
    script = textwrap.dedent(scripts[index]).replace(
        "9>/var/lock/banano-kling-production-deploy.lock",
        '9>"$PROJECT_DIR/deploy.lock"',
    )
    if index == 1:
        # Exercise the local fallback's real success report too: it must not
        # reference a shell variable removed from the checkout transaction.
        reports = re.findall(r'^          echo "deployed_sha=.*"$', source, re.MULTILINE)
        assert len(reports) == 2
        script += textwrap.dedent(reports[index]) + "\n"
    return script


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Deploy Test", "-c", "user.email=deploy@example.invalid", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture(params=DEPLOY_PATHS, ids=["reliable-ssh", "fallback-ssh", "fallback-local"])
def deploy_repo(tmp_path, request, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "tanyapi")
    (origin / "data").mkdir()
    (origin / PRICE).write_text(json.dumps({"default_cost": 4}))
    (origin / "app.txt").write_text("old application")
    (origin / "obsolete.txt").write_text("delete on release")
    (origin / "rename-me.txt").write_text("rename on release")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "Baseline")
    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", str(origin), str(checkout))
    backups = tmp_path / "backups"
    backups.mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "docker").write_text("#!/bin/sh\nexit 99\n")
    (binaries / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TMPDIR", str(backups))
    script = tmp_path / "checkout.sh"
    script.write_text(_checkout_script(*request.param))
    return origin, checkout, backups, binaries, script


def _deploy(deploy_repo, *, force=False, changed=False, runtime=ADMIN_PRICE, remove_default=False, target_layout=None):
    origin, checkout, _, _, script = deploy_repo
    default = {"default_cost": 6 if changed else 4}
    if force:
        default["force_apply_runtime_price"] = True
    if remove_default:
        _git(origin, "rm", PRICE)
    else:
        (origin / PRICE).write_text(json.dumps(default))
    (origin / "app.txt").write_text("new application")
    (origin / "obsolete.txt").unlink()
    (origin / "rename-me.txt").rename(origin / "renamed.txt")
    (origin / "new.txt").write_text("new source")
    if target_layout:
        (origin / PRICE).unlink()
        if target_layout == "price-directory":
            (origin / PRICE).mkdir()
            (origin / PRICE / "child.txt").write_text("not a runtime price file")
        else:
            (origin / "data").rmdir()
            if target_layout == "data-file":
                (origin / "data").write_text("would replace the runtime parent")
            else:
                (origin / "data").symlink_to("app.txt")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "Release")
    expected_sha = _git(origin, "rev-parse", "HEAD")
    if runtime is None:
        (checkout / PRICE).unlink()
    else:
        (checkout / PRICE).write_bytes(runtime)
    result = subprocess.run(
        ["bash", str(script), str(checkout), expected_sha],
        cwd=checkout, capture_output=True, text=True, timeout=15, check=False,
    )
    return result, expected_sha


@pytest.mark.parametrize("force,changed", [(False, False), (True, False), (False, True), (True, True)])
def test_admin_bytes_survive_standard_deploy(deploy_repo, force, changed):
    result, expected_sha = _deploy(deploy_repo, force=force, changed=changed)
    _, checkout, backups, _, _ = deploy_repo
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE
    assert not (checkout / "obsolete.txt").exists()
    assert not (checkout / "rename-me.txt").exists()
    assert (checkout / "renamed.txt").read_text() == "rename on release"
    assert (checkout / "new.txt").read_text() == "new source"
    assert (checkout / "app.txt").read_text() == "new application"
    assert _git(checkout, "write-tree") == _git(checkout, "rev-parse", "HEAD^{tree}")
    assert not list(backups.iterdir())


def test_missing_runtime_price_uses_checked_in_default(deploy_repo):
    result, expected_sha = _deploy(deploy_repo, force=True, changed=True, runtime=None)
    origin, checkout, backups, _, _ = deploy_repo
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert (checkout / PRICE).read_bytes() == (origin / PRICE).read_bytes()
    assert not list(backups.iterdir())


@pytest.mark.parametrize("runtime", [b'{"broken":', b'[]\n', b'null\n'])
def test_invalid_runtime_price_aborts_without_replacement(deploy_repo, runtime):
    _, checkout, _, _, _ = deploy_repo
    initial_sha = _git(checkout, "rev-parse", "HEAD")
    result, _ = _deploy(deploy_repo, force=True, changed=True, runtime=runtime)
    assert result.returncode != 0
    assert (checkout / PRICE).read_bytes() == runtime
    assert _git(checkout, "rev-parse", "HEAD") == initial_sha


def test_admin_bytes_survive_versioned_default_removal(deploy_repo):
    result, expected_sha = _deploy(deploy_repo, remove_default=True)
    _, checkout, _, _, _ = deploy_repo
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE


def test_index_reset_failure_preserves_admin_bytes_and_retains_backup(deploy_repo):
    _, checkout, backups, binaries, _ = deploy_repo
    real_git = shutil.which("git")
    wrapper = binaries / "git"
    wrapper.write_text(
        '#!/bin/bash\n"' + real_git + '" "$@"\nstatus=$?\n'
        'if [ "$1" = reset ]; then exit 91; fi\nexit "$status"\n'
    )
    wrapper.chmod(0o755)
    result, _ = _deploy(deploy_repo)
    assert result.returncode == 91, result.stdout + result.stderr
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE
    retained = list(backups.iterdir())
    assert len(retained) == 1
    assert retained[0].read_bytes() == ADMIN_PRICE
    assert str(retained[0]) in result.stderr


def test_checkout_never_copies_over_existing_runtime(deploy_repo):
    _, _, backups, binaries, _ = deploy_repo
    real_cp = shutil.which("cp")
    wrapper = binaries / "cp"
    wrapper.write_text(
        '#!/bin/bash\nif [ "${@: -1}" = "data/price.json" ]; then exit 92; fi\n'
        'exec "' + real_cp + '" "$@"\n'
    )
    wrapper.chmod(0o755)
    result, _ = _deploy(deploy_repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(backups.iterdir())


def test_partial_backup_failure_leaves_runtime_and_checkout_untouched(deploy_repo):
    _, checkout, _, binaries, _ = deploy_repo
    initial_sha = _git(checkout, "rev-parse", "HEAD")
    real_cp = shutil.which("cp")
    wrapper = binaries / "cp"
    wrapper.write_text(
        '#!/bin/bash\ncase "${@: -1}" in "$TMPDIR"/*)\n'
        'printf partial > "${@: -1}"; exit 92;; esac\n'
        'exec "' + real_cp + '" "$@"\n'
    )
    wrapper.chmod(0o755)
    result, _ = _deploy(deploy_repo)
    assert result.returncode == 92, result.stdout + result.stderr
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE
    assert _git(checkout, "rev-parse", "HEAD") == initial_sha


def test_later_deploy_failure_does_not_revert_new_admin_edit(deploy_repo, monkeypatch):
    _, checkout, backups, _, script = deploy_repo
    later_price = '{"later_admin_change": 17}\n'
    monkeypatch.setenv("LATER_ADMIN_PRICE", later_price)
    with script.open("a") as output:
        output.write('printf "%s" "$LATER_ADMIN_PRICE" > "$RUNTIME_PRICE_FILE"\nexit 93\n')
    result, _ = _deploy(deploy_repo)
    assert result.returncode == 93, result.stdout + result.stderr
    assert (checkout / PRICE).read_text() == later_price
    retained = list(backups.iterdir())
    assert len(retained) == 1
    assert retained[0].read_bytes() == ADMIN_PRICE


def test_unrelated_tracked_drift_blocks_before_reset(deploy_repo):
    _, checkout, backups, _, _ = deploy_repo
    initial_sha = _git(checkout, "rev-parse", "HEAD")
    (checkout / "app.txt").write_text("local change")
    result, _ = _deploy(deploy_repo)
    assert result.returncode != 0
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE
    assert (checkout / "app.txt").read_text() == "local change"
    assert _git(checkout, "rev-parse", "HEAD") == initial_sha
    assert not list(backups.iterdir())


def test_unchanged_versioned_force_flag_preserves_admin_bytes(deploy_repo):
    origin, checkout, _, _, _ = deploy_repo
    (origin / PRICE).write_text(json.dumps({"default_cost": 4, "force_apply_runtime_price": True}))
    _git(origin, "commit", "-am", "Existing legacy force flag")
    _git(checkout, "fetch", "origin", "tanyapi")
    _git(checkout, "reset", "--hard", "origin/tanyapi")
    result, expected_sha = _deploy(deploy_repo, force=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE


def test_clean_runtime_price_survives_changed_default(deploy_repo):
    _, checkout, _, _, _ = deploy_repo
    old_default = (checkout / PRICE).read_bytes()
    result, expected_sha = _deploy(deploy_repo, changed=True, runtime=old_default)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert (checkout / PRICE).read_bytes() == old_default


@pytest.mark.parametrize("initial_runtime", [ADMIN_PRICE, None], ids=["existing", "appeared-during-checkout"])
@pytest.mark.parametrize("write_before", ["restore", "reset"])
def test_concurrent_admin_save_survives_git_update(deploy_repo, monkeypatch, initial_runtime, write_before):
    _, checkout, _, binaries, _ = deploy_repo
    later_price = '{"concurrent_admin_price": 17}\n'
    monkeypatch.setenv("CONCURRENT_ADMIN_PRICE", later_price)
    monkeypatch.setenv("ADMIN_WRITE_BEFORE", write_before)
    real_git = shutil.which("git")
    wrapper = binaries / "git"
    wrapper.write_text(
        '#!/bin/bash\nif [ "$1" = "$ADMIN_WRITE_BEFORE" ]; then\n'
        'mkdir -p data; printf "%s" "$CONCURRENT_ADMIN_PRICE" > data/price.json\nfi\n'
        'exec "' + real_git + '" "$@"\n'
    )
    wrapper.chmod(0o755)
    result, expected_sha = _deploy(deploy_repo, force=True, changed=True, runtime=initial_runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (checkout / PRICE).read_text() == later_price
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha
    assert _git(checkout, "write-tree") == _git(checkout, "rev-parse", "HEAD^{tree}")


def test_first_install_cannot_clobber_admin_file_created_during_seeding(deploy_repo, monkeypatch):
    _, checkout, _, binaries, _ = deploy_repo
    later_price = '{"admin_price_created_during_seed": 19}\n'
    monkeypatch.setenv("CONCURRENT_ADMIN_PRICE", later_price)
    real_ln = shutil.which("ln")
    wrapper = binaries / "ln"
    wrapper.write_text(
        '#!/bin/bash\nprintf "%s" "$CONCURRENT_ADMIN_PRICE" > data/price.json\n'
        'exec "' + real_ln + '" "$@"\n'
    )
    wrapper.chmod(0o755)
    result, expected_sha = _deploy(deploy_repo, force=True, changed=True, runtime=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (checkout / PRICE).read_text() == later_price
    assert _git(checkout, "rev-parse", "HEAD") == expected_sha


def test_wrong_checked_out_branch_is_rejected_without_writes(deploy_repo):
    _, checkout, _, _, _ = deploy_repo
    _git(checkout, "switch", "-c", "unrelated-investigation")
    initial_sha = _git(checkout, "rev-parse", "HEAD")
    result, _ = _deploy(deploy_repo)
    assert result.returncode != 0
    assert _git(checkout, "branch", "--show-current") == "unrelated-investigation"
    assert _git(checkout, "rev-parse", "HEAD") == initial_sha
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE


@pytest.mark.parametrize("target_layout", ["data-file", "data-symlink", "price-directory"])
def test_conflicting_runtime_tree_shape_aborts_before_source_update(deploy_repo, target_layout):
    _, checkout, backups, _, _ = deploy_repo
    initial_sha = _git(checkout, "rev-parse", "HEAD")
    result, _ = _deploy(deploy_repo, target_layout=target_layout)
    assert result.returncode != 0
    assert (checkout / PRICE).read_bytes() == ADMIN_PRICE
    assert (checkout / "app.txt").read_text() == "old application"
    assert _git(checkout, "rev-parse", "HEAD") == initial_sha
    assert not list(backups.iterdir())


def test_existing_runtime_inode_and_permissions_survive(deploy_repo):
    _, checkout, _, _, _ = deploy_repo
    price = checkout / PRICE
    price.chmod(0o640)
    before = price.stat()
    result, _ = _deploy(deploy_repo, changed=True, force=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert price.stat().st_ino == before.st_ino
    assert price.stat().st_mode == before.st_mode
    assert price.read_bytes() == ADMIN_PRICE


def test_source_update_failure_keeps_concurrent_admin_save_and_backup(deploy_repo, monkeypatch):
    _, checkout, backups, binaries, _ = deploy_repo
    later_price = '{"concurrent_admin_on_failure": 23}\n'
    monkeypatch.setenv("CONCURRENT_ADMIN_PRICE", later_price)
    real_git = shutil.which("git")
    wrapper = binaries / "git"
    wrapper.write_text(
        '#!/bin/bash\n"' + real_git + '" "$@"\nstatus=$?\n'
        'if [ "$1" = restore ]; then\n'
        'printf "%s" "$CONCURRENT_ADMIN_PRICE" > data/price.json; exit 94\nfi\n'
        'exit "$status"\n'
    )
    wrapper.chmod(0o755)
    result, _ = _deploy(deploy_repo, changed=True)
    assert result.returncode == 94, result.stdout + result.stderr
    assert (checkout / PRICE).read_text() == later_price
    retained = list(backups.iterdir())
    assert len(retained) == 1
    assert retained[0].read_bytes() == ADMIN_PRICE
