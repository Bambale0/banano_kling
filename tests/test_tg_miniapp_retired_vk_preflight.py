"""Regression: Telegram-only frontend publishing must never require retired VK DNS."""

import os
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "scripts/deploy_miniapp_local.sh"


def _preflight(*, enabled=None, curl_exit=6):
    source = DEPLOY.read_text(encoding="utf-8")
    first = source.find('VK_MINIAPP_DEPLOY_ENABLED="${VK_MINIAPP_DEPLOY_ENABLED:-0}"')
    if first == -1:  # original implementation, before the fix (TDD red)
        first = source.index('VK_BASE_URL="https://${VK_FRONTEND_DOMAIN}"')
    last = source.index('log "Building exact commit', first)
    # Exercise the actual preflight block with local stubbed network and disk,
    # not the deploy's npm/build/production side effects.
    preflight = source[first:last]
    stub = '''set -Eeuo pipefail
VK_FRONTEND_DOMAIN="vk.example.invalid"
VK_RELEASE_ROOT="/tmp/not-a-production-vk-root"
log() { :; }
die() { printf 'DIE:%s\\n' "$*" >&2; exit 70; }
require_disk_space() { :; }
curl() { printf 'CALLED_VK_CURL\\n' >&2; printf '200'; return "$CURL_EXIT"; }
'''
    env = os.environ.copy()
    env["CURL_EXIT"] = str(curl_exit)
    env.pop("VK_MINIAPP_DEPLOY_ENABLED", None)
    if enabled is not None:
        env["VK_MINIAPP_DEPLOY_ENABLED"] = enabled
    return subprocess.run(
        ["bash", "-c", stub + preflight + '\nprintf "VK_ISOLATED=%s\\n" "$VK_ISOLATED"'],
        check=False, capture_output=True, text=True, timeout=5, env=env,
    )


def test_retired_vk_dns_is_never_required_for_default_telegram_deploy():
    result = _preflight(curl_exit=6)
    assert result.returncode == 0, result.stderr
    assert "CALLED_VK_CURL" not in result.stderr
    assert "VK_ISOLATED=1" in result.stdout


def test_explicit_vk_opt_in_preserves_legacy_required_preflight():
    result = _preflight(enabled="1", curl_exit=0)
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("CALLED_VK_CURL") == 2
    assert "VK_ISOLATED=0" in result.stdout


def test_explicit_vk_opt_in_rejects_unavailable_host():
    result = _preflight(enabled="1", curl_exit=6)
    assert result.returncode != 0


def test_final_vk_smoke_is_not_invoked_in_telegram_only_mode():
    source = DEPLOY.read_text(encoding="utf-8")
    assert 'if [[ "$VK_MINIAPP_DEPLOY_ENABLED" == "1" ]]; then\n  vk_mode=' in source
    assert 'log "VK_DEPLOY_SKIPPED' in source
    assert '[[ "$live_revision" == "$EXPECTED_SHA" ]]' in source


def test_invalid_vk_opt_in_is_rejected_before_any_network_request():
    result = _preflight(enabled="unexpected", curl_exit=0)
    assert result.returncode != 0
    assert "VK_MINIAPP_DEPLOY_ENABLED must be 0 or 1" in result.stderr
    assert "CALLED_VK_CURL" not in result.stderr
