from pathlib import Path

COMPAT_SOURCE = Path("bot/handlers/own_profile_feed_compat.py").read_text(
    encoding="utf-8"
)
HANDLERS_SOURCE = Path("bot/handlers/__init__.py").read_text(encoding="utf-8")


def test_authenticated_user_is_authoritative_for_own_referral_code():
    assert "referral_code == viewer_referral_code" in COMPAT_SOURCE
    assert "author = viewer" in COMPAT_SOURCE
    assert "get_user_by_referral_code(referral_code)" in COMPAT_SOURCE


def test_profile_response_disables_caching():
    assert 'response.headers["Cache-Control"]' in COMPAT_SOURCE
    assert 'response.headers["Pragma"] = "no-cache"' in COMPAT_SOURCE


def test_compat_is_installed_before_routes_are_built():
    assert "from .own_profile_feed_compat import install_own_profile_feed_compat" in HANDLERS_SOURCE
    assert "install_own_profile_feed_compat()" in HANDLERS_SOURCE
