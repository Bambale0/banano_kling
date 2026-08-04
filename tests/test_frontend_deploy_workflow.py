from pathlib import Path


OBSOLETE_REMOTE_WORKFLOWS = (
    Path(".github/workflows/deploy-frontend-production.yml"),
    Path(".github/workflows/deploy-frontend.yml"),
)


def test_obsolete_remote_frontend_workflows_are_removed() -> None:
    for workflow in OBSOLETE_REMOTE_WORKFLOWS:
        assert not workflow.exists(), (
            f"{workflow} still deploys the Mini App through the retired remote/CDN flow"
        )


def test_miniapp_ci_validates_contract_and_static_build_without_deploying() -> None:
    workflow = Path(".github/workflows/miniapp-ci.yml").read_text(encoding="utf-8")

    assert "lib/__tests__/trend-api.test.ts" in workflow
    assert "npm run build" in workflow
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-node@v6" in workflow

    forbidden_remote_markers = (
        "FRONTEND_SSH_HOST",
        "cdn.chillcreative.ru",
        "tanyafrontend",
        "--remote-deploy",
    )
    for marker in forbidden_remote_markers:
        assert marker not in workflow
