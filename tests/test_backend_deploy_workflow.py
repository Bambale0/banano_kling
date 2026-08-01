from pathlib import Path


WORKFLOW = Path(".github/workflows/deploy-production.yml")


def test_backend_deploy_tries_github_then_nuromix() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github_ssh_deploy:" in text
    assert "nuromix_deploy:" in text
    assert "needs: [ci_gate, github_ssh_deploy]" in text
    assert "runs-on: [self-hosted, linux, x64, nuromix]" in text
    assert "needs.github_ssh_deploy.outputs.passed != 'true'" in text


def test_backend_deploy_cannot_finish_green_without_a_deployment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "deployment_gate:" in text
    assert "Require one successful deployment path" in text
    assert "Production was not deployed" in text
    assert "falling back to self-hosted nuromix" in text
