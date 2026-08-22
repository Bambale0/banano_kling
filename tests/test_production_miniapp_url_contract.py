from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_MINI_APP_URL = "https://tanyapp.xn--e1aikcel5c5a.online/mini-app/"


def test_production_backend_deploy_pins_frontend_url_only_on_tanyapi():
    deploy = (ROOT / "scripts/deploy_backend_docker.sh").read_text(encoding="utf-8")

    assert 'PRODUCTION_BRANCH="${PRODUCTION_BRANCH:-tanyapi}"' in deploy
    assert PRODUCTION_MINI_APP_URL in deploy
    assert "if is_production_branch; then" in deploy
    assert 'export MINI_APP_URL="$PRODUCTION_MINI_APP_URL"' in deploy
    assert "verify_configured_miniapp_url" in deploy
    assert "verify_running_miniapp_url" in deploy
    assert "production MINI_APP_URL mismatch before cutover" in deploy
    assert "running production MINI_APP_URL mismatch" in deploy


def test_backend_and_static_production_deploy_share_the_same_miniapp_url():
    backend_deploy = (ROOT / "scripts/deploy_backend_docker.sh").read_text(
        encoding="utf-8"
    )
    frontend_deploy = (ROOT / "scripts/deploy_miniapp_local.sh").read_text(
        encoding="utf-8"
    )
    production_workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text(
        encoding="utf-8"
    )

    assert PRODUCTION_MINI_APP_URL in backend_deploy
    assert "tanyapp.xn--e1aikcel5c5a.online" in frontend_deploy
    assert "tanyapp.xn--e1aikcel5c5a.online/mini-app/revision.txt" in production_workflow
