"""Server-side Astro role protection does not trust UI-only admin flags."""

import pytest
from aiohttp import web

from bot import astro_api


def test_missing_data_or_vk_session_are_never_authorized():
    for init_data in ("", None, "vk_session:" + "a" * 43):
        with pytest.raises(web.HTTPUnauthorized):
            astro_api.assert_admin_astro_access(init_data, 1, "telegram")


def test_non_admin_and_vk_are_forbidden(monkeypatch):
    monkeypatch.setattr(astro_api.config, "is_admin", lambda user_id: user_id == 5)
    with pytest.raises(web.HTTPForbidden):
        astro_api.assert_admin_astro_access("signed", 4, "telegram")
    with pytest.raises(web.HTTPForbidden):
        astro_api.assert_admin_astro_access("signed", 5, "vk")
    astro_api.assert_admin_astro_access("signed", 5, "telegram")
