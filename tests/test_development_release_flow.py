ROOT = __file__.rsplit("tests/test_development_release_flow.py", 1)[0]


def read(path: str) -> str:
    with open(f"{ROOT}{path}", encoding="utf-8") as file:
        return file.read()


def test_development_ci_targets_only_dev() -> None:
    workflow = read(".github/workflows/ci-development.yml")

    assert "branches: [dev]" in workflow
    assert "tanyapi" not in workflow
    assert "branches: [main]" not in workflow


def test_development_ci_uses_current_browser_e2e_gate() -> None:
    workflow = read(".github/workflows/ci-development.yml")

    assert "npm audit --audit-level=high" in workflow
    assert "npm run lint" in workflow
    assert "npm run build" in workflow
    assert "npx playwright install --with-deps chromium" in workflow
    assert "node e2e/critical-flows.mjs" in workflow
    assert "npm test" not in workflow


def test_development_backend_deploy_isolated_from_production_secrets() -> None:
    workflow = read(".github/workflows/deploy-development.yml")

    assert "branches: [dev]" in workflow
    assert "environment: development" in workflow
    assert 'GITHUB_REF" = "refs/heads/dev' in workflow
    assert "DEV_SSH_HOST" in workflow
    assert "DEV_PROJECT_PATH" in workflow
    assert "PROD_" not in workflow
    assert "git fetch --prune origin dev" in workflow
    assert 'remote_sha="$(git rev-parse origin/dev)"' in workflow
    assert '"$remote_sha" = "$EXPECTED_SHA"' in workflow
    assert "git switch dev" in workflow
    assert "banano-kling-dev-bot" in workflow


def test_development_frontend_deploy_isolated_from_production() -> None:
    workflow = read(".github/workflows/deploy-frontend-development.yml")

    assert "branches: [dev]" in workflow
    assert "environment: development" in workflow
    assert 'GITHUB_REF" = "refs/heads/dev' in workflow
    assert "DEV_API_BASE_URL" in workflow
    assert "DEV_FRONTEND_DOMAIN" in workflow
    assert "PROD_" not in workflow
    assert "git fetch --prune origin dev" in workflow
    assert 'remote_sha="$(git rev-parse origin/dev)"' in workflow
    assert '"$remote_sha" = "$EXPECTED_SHA"' in workflow
    assert "REPO_BRANCH:-}" in workflow
    assert "BACKEND_ORIGIN%/" in workflow
    assert "git switch dev" in workflow
    assert "npm run build" in workflow
    assert "npm test" not in workflow


def test_production_backend_deploy_remains_on_tanyapi() -> None:
    workflow = read(".github/workflows/deploy-production.yml")

    assert "branches: [tanyapi]" in workflow
    assert "git fetch --prune origin tanyapi" in workflow
    assert "git switch tanyapi" in workflow
    assert "branches: [main]" not in workflow


def test_production_frontend_is_validated_on_tanyapi_without_remote_deploy() -> None:
    try:
        read(".github/workflows/deploy-frontend-production.yml")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Retired remote frontend deployment workflow still exists")

    workflow = read(".github/workflows/miniapp-ci.yml")
    assert "branches: [tanyapi]" in workflow
    assert "lib/__tests__/trend-api.test.ts" in workflow
    assert "npm run build" in workflow
    assert "FRONTEND_SSH_HOST" not in workflow
    assert "cdn.chillcreative.ru" not in workflow
    assert "branches: [main]" not in workflow


def test_compose_supports_parallel_dev_and_production_projects() -> None:
    compose = read("compose.backend.yml")

    assert "name: ${COMPOSE_PROJECT_NAME:-banano-kling}" in compose
    assert "container_name: ${CONTAINER_NAME:-banano-kling-bot}" in compose
