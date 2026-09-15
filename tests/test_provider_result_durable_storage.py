import asyncio
from unittest.mock import AsyncMock

import bot.main as main_module
from bot.config import config
from bot.services import feed_persist
from scripts import backfill_rendergrid_image_results as backfill


def test_rendergrid_image_result_is_durable_even_when_global_persist_is_off(monkeypatch):
    external_url = "https://cdn.rendergrid.io/images/2026/09/15/result.png"
    durable_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/result.png"
    persist_mock = AsyncMock(return_value=[durable_url])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="image")
    )

    assert result == durable_url
    persist_mock.assert_awaited_once_with([external_url], require_local=True)


def test_non_durable_image_host_respects_global_persist_flag(monkeypatch):
    external_url = "https://example.com/result.png"
    persist_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="image")
    )

    assert result == external_url
    persist_mock.assert_not_awaited()



def test_rendergrid_backfill_detects_only_provider_result_host():
    assert backfill._is_rendergrid_result_url(
        "https://cdn.rendergrid.io/images/2026/09/15/result.png"
    )
    assert not backfill._is_rendergrid_result_url(
        "https://example.com/images/result.png"
    )


def test_rendergrid_backfill_rewrites_result_urls_without_losing_extras():
    old_url = "https://cdn.rendergrid.io/images/old.png"
    extra_url = "https://example.com/extra.png"
    durable_url = "https://tanyapi.chillcreative.ru/uploads/feed/durable.png"

    result = backfill._replace_result_url_list(
        f'["{old_url}", "{extra_url}", "{old_url}"]',
        old_url=old_url,
        new_url=durable_url,
    )

    assert result == f'["{durable_url}", "{extra_url}"]'
