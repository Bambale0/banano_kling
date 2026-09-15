from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTO_MERGE = ROOT / ".github/workflows/tanyapi-auto-merge.yml"
CI = ROOT / ".github/workflows/ci.yml"
RELIABLE_DEPLOY = ROOT / ".github/workflows/deploy-production-reliable.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_auto_merge_targets_only_tanyapi_pull_requests() -> None:
    source = _read(AUTO_MERGE)

    assert "pull_request_target:" in source
    assert "branches: [tanyapi]" in source
    assert "base.ref == 'tanyapi'" in source
    assert "branches: [main]" not in source
    assert "branches: [dev]" not in source


def test_auto_merge_never_checks_out_pr_code_with_write_token() -> None:
    source = _read(AUTO_MERGE)

    assert "actions: write" in source
    assert "pull-requests: write" in source
    assert "contents: write" in source
    assert "actions/checkout" not in source
    assert "head.repo.full_name == github.repository" in source
    assert "group: tanyapi-auto-merge" in source
    assert "cancel-in-progress: false" in source


def test_auto_merge_waits_for_exact_head_and_every_registered_pr_workflow() -> None:
    source = _read(AUTO_MERGE)

    assert "EXPECTED_HEAD_SHA" in source
    assert '-f head_sha="$EXPECTED_HEAD_SHA"' in source
    assert "-f event=pull_request" in source
    assert 'select(.status != "completed")' in source
    assert 'select(.status == "completed" and .conclusion != "success")' in source
    assert 'select(.name == "CI — Tanya TG Bot"' in source
    assert 'pulls/${PR_NUMBER}/merge' in source
    assert '-f sha="$EXPECTED_HEAD_SHA"' in source
    assert "-f merge_method=squash" in source
    assert "--auto" not in source


def test_auto_merge_explicitly_dispatches_exact_post_merge_ci_and_deploy() -> None:
    source = _read(AUTO_MERGE)
    ci = _read(CI)
    deploy = _read(RELIABLE_DEPLOY)

    assert "workflow_dispatch:" in ci
    assert 'gh workflow run ci.yml' in source
    assert "-f event=workflow_dispatch" in source
    assert 'gh workflow run deploy-production-reliable.yml' in source
    assert "workflow_dispatch:" in deploy
    assert 'ci_event=workflow_dispatch' in deploy
    assert '-f event="$ci_event"' in deploy
