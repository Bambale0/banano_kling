from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/tanyapi-auto-merge.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_auto_merge_targets_only_tanyapi_pull_requests() -> None:
    source = _workflow()

    assert "pull_request_target:" in source
    assert "branches: [tanyapi]" in source
    assert "base.ref == 'tanyapi'" in source
    assert "branches: [main]" not in source
    assert "branches: [dev]" not in source


def test_auto_merge_never_checks_out_pr_code_with_write_token() -> None:
    source = _workflow()

    assert "pull-requests: write" in source
    assert "contents: write" in source
    assert "actions/checkout" not in source
    assert "head.repo.full_name == github.repository" in source


def test_auto_merge_uses_native_required_check_gate_and_squash() -> None:
    source = _workflow()

    assert 'gh pr merge "$PR_NUMBER"' in source
    assert "--auto" in source
    assert "--squash" in source
    assert "draft == false" in source
