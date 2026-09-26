from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PENDING_WORKFLOW = ROOT / ".github/workflows/publish-pipeline-pending-status.yml"
RELIABLE_DEPLOY_WORKFLOW = ROOT / ".github/workflows/deploy-production-reliable.yml"


def test_pending_status_links_to_active_reliable_deploy_workflow() -> None:
    workflow = PENDING_WORKFLOW.read_text(encoding="utf-8")

    assert "publish_pending deploy-production-reliable.yml tanya/deploy" in workflow
    assert "publish_pending deploy-production.yml tanya/deploy" not in workflow


def test_reliable_deploy_publishes_terminal_tanya_deploy_status() -> None:
    workflow = RELIABLE_DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "publish_status:" in workflow
    assert "if: always()" in workflow
    assert "context='tanya/deploy'" in workflow
    assert 'DEPLOY_RESULT: ${{ needs.deploy.result }}' in workflow
    assert 'VERIFY_RESULT: ${{ needs.verify_ci.result }}' in workflow
    assert 'state=success' in workflow
    assert 'state=failure' in workflow
