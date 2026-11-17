"""Regression: Telegram-only production publisher must not depend on retired VK DNS."""
from pathlib import Path


def test_miniapp_publisher_does_not_probe_retired_vk_host():
    script = (Path(__file__).resolve().parents[1] / "scripts" / "deploy_miniapp_local.sh").read_text()
    assert "VK_ISOLATED=1" in script
    assert "vk_revision_code=" not in script
    assert "vk_index_code=" not in script
    assert "verify_vk_miniapp_mode.sh" not in script
    assert 'live_revision="$(' in script
    assert '[[ "$live_revision" == "$EXPECTED_SHA" ]]' in script
