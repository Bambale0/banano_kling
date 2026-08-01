from pathlib import Path


def test_frontend_deploy_uses_pinned_checkout_installer() -> None:
    workflow = Path(".github/workflows/deploy-frontend-production.yml").read_text(
        encoding="utf-8"
    )

    assert 'git reset --hard "$EXPECTED_SHA"' in workflow
    assert 'bash "$INSTALLER" --config "$PROFILE" --deploy-only' in workflow
    assert 'bash cdn.sh --deploy-domain "$DOMAIN"' not in workflow
    assert 'deployed_sha="$(git rev-parse HEAD)"' in workflow
    assert 'cmp -s "$source_index" "$deployed_index"' in workflow


def test_frontend_runner_fallback_is_limited_to_nuromix() -> None:
    workflow = Path(".github/workflows/deploy-frontend-production.yml").read_text(
        encoding="utf-8"
    )

    assert "runs-on: [self-hosted, linux, x64, nuromix]" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "github.ref == 'refs/heads/tanyapi'" in workflow
