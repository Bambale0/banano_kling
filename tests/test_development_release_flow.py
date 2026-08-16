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


def test_production_frontend_is_built_on_the_same_server() -> None:
    for retired in (
        ".github/workflows/deploy-frontend-production.yml",
        ".github/workflows/deploy-miniapp-production.yml",
    ):
        try:
            read(retired)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError(f"Retired standalone frontend deploy still exists: {retired}")

    ci_workflow = read(".github/workflows/miniapp-ci.yml")
    assert "branches: [tanyapi]" in ci_workflow
    assert "lib/__tests__/trend-api.test.ts" in ci_workflow
    assert "components/tabs/__tests__/video-tab-repeat.test.tsx" in ci_workflow
    assert "npm run build" in ci_workflow
    assert "self-hosted" not in ci_workflow
    assert "branches: [main]" not in ci_workflow

    deploy_workflow = read(".github/workflows/deploy-production.yml")
    assert "branches: [tanyapi]" in deploy_workflow
    assert "PROD_SSH_HOST" in deploy_workflow
    assert "PROD_SSH_PRIVATE_KEY" in deploy_workflow
    assert 'remote_sha="$(git rev-parse origin/tanyapi)"' in deploy_workflow
    assert '"$remote_sha" = "$EXPECTED_SHA"' in deploy_workflow
    assert 'scripts/deploy_miniapp_local.sh "$EXPECTED_SHA"' in deploy_workflow
    assert "tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt" in deploy_workflow
    assert "tanyafrontend" not in deploy_workflow
    assert "cdn.chillcreative.ru" not in deploy_workflow
    assert "--remote-deploy" not in deploy_workflow
    assert "branches: [main]" not in deploy_workflow

    deploy_script = read("scripts/deploy_miniapp_local.sh")
    assert 'DEFAULT_FRONTEND_DOMAIN="tanyapp.xn--e1aikcel5c5a.online"' in deploy_script
    assert 'npm ci' in deploy_script
    assert 'npm run lint' in deploy_script
    assert 'npm run build' in deploy_script
    assert 'rsync -a' in deploy_script
    assert 'revision.txt' in deploy_script
    assert 'cdn.chillcreative.ru' not in deploy_script


def test_compose_supports_parallel_dev_and_production_projects() -> None:
    compose = read("compose.backend.yml")

    assert "name: ${COMPOSE_PROJECT_NAME:-banano-kling}" in compose
    assert "container_name: ${CONTAINER_NAME:-banano-kling-bot}" in compose
