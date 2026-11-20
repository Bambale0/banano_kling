"""Wan3 website/document inputs: owned, sniffed, bounded and SSRF-safe."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from bot import web_auth, web_generation, web_references
from bot.services.preset_manager import preset_manager
from bot.services.wan3_prime_media import MediaInfo


def test_document_extension_and_signature_cannot_be_forged():
    assert web_references._document_type(
        b"%PDF-1.7\nbody", "report.pdf",
    ) == ("pdf", "application/pdf")
    assert web_references._document_type(
        b"A quick note on video editing", "notes.txt",
    ) == ("txt", "text/plain")
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w") as archive:
        archive.writestr("word/document.xml", "<document>hello</document>")
    assert web_references._document_type(memory.getvalue(), "letter.docx")[0] == "docx"
    for filename, payload in (
        ("report.pdf", b"not a pdf"),
        ("letter.docx", b"PK\x03\x04fake"),
        ("letter.docx", b"%PDF-1.7"),
        ("photo.png", b"%PDF-1.7"),
        ("notes.txt", b"\x00\x01\x02"),
    ):
        with pytest.raises(ValueError):
            web_references._document_type(payload, filename)


@pytest.mark.asyncio
async def test_document_upload_owned_only_and_web_link_ssrf_rejected(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    monkeypatch.setattr(web_references, "is_s3_enabled", lambda: True)
    monkeypatch.setattr(web_references, "persist_upload_bytes", lambda key, raw, **_:
                        "https://neuromixbot.com/uploads/" + key)
    imported = AsyncMock(return_value={
        "url": "https://www.example.org/page", "content_type": "text/html",
        "size": 2048,
    })
    from bot.services import wan3_prime_storage
    monkeypatch.setattr(wan3_prime_storage, "fetch_public_asset", imported)
    response = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "wan3-web-document-owner",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = response.cookies["nm_web_session"].value
    other = await web_auth._complete_identity(
        SimpleNamespace(), "google", "wan3-web-document-other",
        {"mode": "login", "source": None, "destination": "/login"},
    )
    headers = {"Origin": "https://neuromixbot.com",
               "Cookie": "nm_web_session=" + cookie}
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    async with TestClient(TestServer(app)) as client:
        document = FormData()
        document.add_field("file", b"%PDF-1.4\nSome test content",
                           filename="brief.pdf", content_type="application/pdf")
        uploaded = await client.post(
            "/mini-app/api/web-auth/web-generation/reference",
            data=document, headers=headers,
        )
        assert uploaded.status == 200, await uploaded.text()
        file_id = (await uploaded.json())["reference_id"]
        own_account = await web_auth._session_account(
            SimpleNamespace(cookies={"nm_web_session": cookie}),
        )
        foreign_account = await web_auth._session_account(
            SimpleNamespace(cookies={"nm_web_session": other.cookies["nm_web_session"].value}),
        )
        assert len(await web_references.owned_reference_urls(
            own_account, [file_id], kind="file",
        )) == 1
        with pytest.raises(PermissionError):
            await web_references.owned_reference_urls(
                foreign_account, [file_id], kind="file",
            )
        forbidden = await client.post(
            "/mini-app/api/web-auth/web-generation/link",
            json={"url": "https://127.0.0.1/private"}, headers=headers,
        )
        assert forbidden.status == 400
        imported.assert_not_awaited()
        valid = await client.post(
            "/mini-app/api/web-auth/web-generation/link",
            json={"url": "https://www.example.org/page"}, headers=headers,
        )
        assert valid.status == 200, await valid.text()
        link_id = (await valid.json())["reference_id"]
        assert len(await web_references.owned_reference_urls(
            own_account, [link_id], kind="link",
        )) == 1
        with pytest.raises(PermissionError):
            await web_references.owned_reference_urls(
                foreign_account, [link_id], kind="link",
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,extra_key,kind", (
    ("file", "file_reference_ids", "file"),
    ("link", "link_reference_ids", "link"),
))
async def test_wan3_file_or_link_request_uses_owned_id_not_client_urls(
    monkeypatch, scenario, extra_key, kind,
):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {
        "720p": 2.5,
    })
    payload = {
        "model": "wan_3_prime", "wan_scenario": scenario,
        "request_key": "wan-web-document-" + scenario + "-2026",
        "prompt": "Use the supplied material to create a video",
        "duration": 6, "quality": "720P",
        extra_key: ["wr_" + "f" * 32],
    }
    normalized = web_generation._normalize_request(payload)
    assert normalized[extra_key] == payload[extra_key]
    assert web_generation._price_for_request(normalized) == "15"
    with pytest.raises(ValueError):
        web_generation._normalize_request({
            **payload, "reference_link_urls": ["https://any.example/url"],
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,key", (
    ("file", "reference_file_urls"),
    ("link", "reference_link_urls"),
))
async def test_wan3_file_and_link_reach_existing_provider_without_telegram(
    monkeypatch, scenario, key,
):
    from bot.services.wan3_models import wan3_service_for_model

    provider = wan3_service_for_model("wan_3")
    prepared = AsyncMock(return_value={
        "prompt": "Summarize reference", "resolution": "720P",
        "scenario": scenario,
    })
    submitted = AsyncMock(return_value={"task_id": "wan3-document-verified"})
    monkeypatch.setattr(provider, "prepare_request", prepared)
    monkeypatch.setattr(provider, "submit_prepared", submitted)
    refs = ["https://neuromixbot.com/uploads/web_refs/owned.pdf"] if scenario == "file" else [
        "https://www.example.org/public-article",
    ]
    payload = {
        "model": "wan_3", "prompt": "Animate content",
        "wan_scenario": scenario, "duration": 6, "quality": "720P",
        "aspect_ratio": "16:9",
        "reference_urls": [], "reference_video_urls": [], "reference_audio_urls": [],
        key: refs,
    }
    task, rejected = await web_generation._submit_to_provider(
        "web_" + "c" * 32, payload,
    )
    assert (task, rejected) == ("wan3-document-verified", False)
    assert prepared.await_args.kwargs[key] == refs
    assert "telegram_id" not in prepared.await_args.kwargs
    submitted.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,id_field", (
    ("file", "file_reference_ids"), ("link", "link_reference_ids"),
))
async def test_wan3_document_quote_authenticates_source_before_price(
    monkeypatch, scenario, id_field,
):
    monkeypatch.setattr(preset_manager, "get_video_quality_costs", lambda _: {
        "720p": 2.5,
    })
    monkeypatch.setenv("WEB_AUTH_PUBLIC_ORIGIN", "https://neuromixbot.com")
    response = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "wan-doc-quote-" + scenario,
        {"mode": "login", "source": None, "destination": "/login"},
    )
    cookie = response.cookies["nm_web_session"].value
    other = await web_auth._complete_identity(
        SimpleNamespace(), "yandex", "wan-doc-other-" + scenario,
        {"mode": "login", "source": None, "destination": "/login"},
    )
    other_cookie = other.cookies["nm_web_session"].value
    stored_url = (
        "https://neuromixbot.com/uploads/web_refs/owned.pdf"
        if scenario == "file" else "https://www.example.org/public"
    )
    owner_account = await web_auth._session_account(
        SimpleNamespace(cookies={"nm_web_session": cookie}),
    )
    def owned_lookup(account, refs, *, kind):
        if not refs:
            return []
        if account != owner_account:
            raise PermissionError("Not the owner")
        if kind != scenario:
            raise PermissionError("Wrong uploaded media type")
        return [stored_url]
    monkeypatch.setattr(
        web_references, "owned_reference_urls", AsyncMock(side_effect=owned_lookup),
    )
    def owned_metadata(account, refs, *, kind):
        if refs and account != owner_account:
            raise PermissionError("Not the owner")
        return [
            MediaInfo(kind="file", extension=".pdf", pages=2,
                      size_bytes=12345, url=stored_url)
        ] if refs and kind == "file" else []
    monkeypatch.setattr(
        web_references, "owned_reference_media", AsyncMock(side_effect=owned_metadata),
    )
    from bot.services import wan3_prime_storage
    webpage_probe = AsyncMock(return_value={
        "url": stored_url, "content_type": "text/html", "size": 1024,
    })
    monkeypatch.setattr(wan3_prime_storage, "fetch_public_asset", webpage_probe)
    app = web.Application()
    web_auth.setup_web_auth_routes(app, "/mini-app")
    route = "/mini-app/api/web-auth/web-generation/quote"
    body = {
        "model": "wan_3_prime", "wan_scenario": scenario,
        "prompt": "Make a video using referenced material",
        "quality": "720P", "duration": 6,
        id_field: ["wr_" + "e" * 32],
    }
    async with TestClient(TestServer(app)) as client:
        forbidden = await client.post(route, json=body, headers={
            "Origin": "https://neuromixbot.com",
            "Cookie": "nm_web_session=" + other_cookie,
        })
        assert forbidden.status == 403, await forbidden.text()
        quote = await client.post(route, json=body, headers={
            "Origin": "https://neuromixbot.com",
            "Cookie": "nm_web_session=" + cookie,
        })
        assert quote.status == 200, await quote.text()
        assert float((await quote.json())["price"]) == 15.0
    if scenario == "link":
        assert webpage_probe.await_count == 1
