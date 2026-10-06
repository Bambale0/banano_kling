import asyncio
import json
import shutil
import subprocess
from inspect import unwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from bot import seedance_trend_admin_api as api


@pytest.fixture
def uploaded_trend(monkeypatch, tmp_path):
    from bot import database, miniapp
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_READY", False)
    monkeypatch.setattr(trend_success_compat, "_SCHEMA_LOCK", None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api.config, "is_admin", lambda uid: uid == 9001)
    monkeypatch.setattr(
        miniapp,
        "_get_user_context",
        AsyncMock(return_value=(9001, {"user": SimpleNamespace(id=81)})),
    )
    monkeypatch.setattr(
        api,
        "get_active_seedance_trend_by_upload_fingerprint",
        AsyncMock(return_value=None),
        raising=False,
    )
    create = AsyncMock(return_value={"id": 77})
    monkeypatch.setattr(api, "create_prompt", create)
    approved = {
        "id": 77,
        "model": "seedance_2",
        "prompt_text": "PRIVATE",
        "tags": ["trend", "seedance-private-references"],
        "generation_settings": {"kind": "video", "ratio": "9:16"},
    }
    monkeypatch.setattr(api, "approve_prompt", AsyncMock(return_value=approved))
    monkeypatch.setattr(
        api,
        "persist_feed_result_urls",
        AsyncMock(return_value=["https://test.example/uploads/feed/preview.png"]),
    )
    urls = []
    for name, color in (
        ("face", "red"),
        ("dress", "green"),
        ("extra", "blue"),
        ("preview", "white"),
    ):
        path = Path(f"static/uploads/refs/image/9001/{name}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 640), color).save(path)
        urls.append(f"/uploads/refs/image/9001/{name}.png")
    body = {
        "model": "seedance_2",
        "title": "Dress trend",
        "description": "Your own face",
        "prompt_text": "@Image1 wears @Image2",
        "image_urls": urls[:3],
        "video_urls": [],
        "audio_urls": [],
        "identity_image_index": 1,
        "fixed_image_indices": [2],
        "replaceable_image_indices": [],
        "fixed_video_indices": [],
        "fixed_audio_indices": [],
        "replaceable_video_indices": [],
        "replaceable_audio_indices": [],
        "preview_url": urls[3],
        "preview_type": "image",
        "duration": 5,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "user_fields": [{"key": "age", "label": "Возраст", "type": "number"}],
    }
    app = {}

    class Request:
        def __init__(self, payload):
            self.app = app
            self.payload = payload

        async def json(self):
            return self.payload

    return body, Request, create


@pytest.mark.asyncio
async def test_upload_publishes_private_recipe_without_source_task(uploaded_trend):
    body, request, create = uploaded_trend
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    payload = json.loads(response.text)
    assert payload["prompt"]["prompt_text"] == ""
    assert payload["prompt"]["model"] is None
    kwargs = create.await_args.kwargs
    assert kwargs.get("source_generation_id") is None
    assert kwargs["generation_settings"]["reference_slots"] == [
        {"media_type": "image", "position": 1, "label": "ВАШЕ ЛИЦО"}
    ]
    assert kwargs["generation_settings"]["user_fields"][0]["key"] == "age"
    assert len(kwargs["trend_reference_assets"]) == 1
    assert kwargs["trend_reference_assets"][0]["position"] == 2
    assert "face.png" not in json.dumps(kwargs)
    assert "extra.png" not in json.dumps(kwargs)
    assert "refs/" not in response.text
    api.persist_feed_result_urls.assert_awaited_once_with(
        [body["preview_url"]], require_local=True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"model": "kling"},
        {"duration": 4},
        {"duration": True},
        {"duration": 5.5},
        {"resolution": "garbage"},
        {"aspect_ratio": "adaptive"},
        {"seedance25_video_editing": True},
        {"seedance25_video_editing": "false"},
        {"identity_image_index": True},
        {"identity_image_index": 99},
        {"fixed_image_indices": [2, 2]},
        {"fixed_image_indices": [2.5]},
        {"fixed_image_indices": [1]},
        {"replaceable_image_indices": [2]},
        {"replaceable_image_indices": [1]},
        {"fixed_image_indices": []},
        {"fixed_image_indices": [9]},
        {"prompt_text": ""},
        {"prompt_text": "@Image3 is excluded"},
        {"prompt_text": "x" * 20000},
        {"preview_type": "video"},
        {"preview_url": "https://foreign.test/result.jpg"},
        {"title": "x" * 81},
        {"description": "x" * 241},
        {"image_urls": "not a list"},
        {"user_fields": "invalid"},
    ],
)
async def test_upload_rejects_invalid_recipe_before_persistence(
    uploaded_trend, monkeypatch, change
):
    body, request, create = uploaded_trend
    persist = AsyncMock()
    monkeypatch.setattr(api, "_persist_recipe_assets", persist)
    response = await api.miniapp_admin_publish_seedance_upload_trend(
        request({**body, **change})
    )
    assert response.status == 400, response.text
    persist.assert_not_awaited()
    create.assert_not_awaited()
    api.persist_feed_result_urls.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_url",
    [
        "/uploads/refs/image/9002/extra.png",
        "/uploads/refs/video/9001/extra.png",
        "/uploads/refs/image/9001/../9002/extra.png",
        "/uploads/refs/image/9001/%2e%2e/9002/extra.png",
        "https://evil.test/uploads/refs/image/9001/extra.png",
        "//evil.test/uploads/refs/image/9001/extra.png",
        "/uploads/refs/image/9001/extra.png?token=x",
        "/uploads/refs/image/9001/extra.png#fragment",
        "/uploads/refs/image/9001/missing.png",
        "blob:private",
        "data:image/png;base64,private",
    ],
)
async def test_upload_validates_excluded_owner_and_path(uploaded_trend, bad_url):
    body, request, create = uploaded_trend
    body["image_urls"][2] = bad_url
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_non_admin_before_file_work(uploaded_trend, monkeypatch):
    body, request, create = uploaded_trend
    monkeypatch.setattr(api.config, "is_admin", lambda _uid: False)
    inspect = AsyncMock()
    monkeypatch.setattr(api, "validate_trend_reference_source", inspect)
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 403
    inspect.assert_not_awaited()
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_content", [False, True])
async def test_upload_preview_cannot_expose_reference(uploaded_trend, same_content):
    body, request, create = uploaded_trend
    if same_content:
        Path("static" + body["preview_url"]).write_bytes(
            Path("static" + body["image_urls"][1]).read_bytes()
        )
    else:
        body["preview_url"] = body["image_urls"][1]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_content", [False, True])
async def test_upload_rejects_duplicate_media(uploaded_trend, same_content):
    body, request, create = uploaded_trend
    if same_content:
        Path("static" + body["image_urls"][2]).write_bytes(
            Path("static" + body["image_urls"][0]).read_bytes()
        )
    else:
        body["image_urls"][2] = body["image_urls"][0]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_forged_image_bytes_in_excluded_input(uploaded_trend):
    body, request, create = uploaded_trend
    Path("static" + body["image_urls"][2]).write_bytes(b"not an image")
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_symlink_to_foreign_owner(uploaded_trend):
    body, request, create = uploaded_trend
    foreign = Path("static/uploads/refs/image/9002/foreign.png")
    foreign.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 640), "black").save(foreign)
    owned = Path("static/uploads/refs/image/9001/link.png")
    owned.symlink_to(foreign.resolve())
    body["image_urls"][2] = "/uploads/refs/image/9001/link.png"
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


def add_typed_upload(kind, name, data):
    path = Path(f"static/uploads/refs/{kind}/9001/{name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for synthetic playable media")
    source = (
        "color=c=red:s=640x640:r=24:d=5"
        if kind == "video"
        else (
            "sine=frequency=440:duration=5"
            if "fixed" in name
            else "sine=frequency=550:duration=5"
        )
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, "-y", str(path)],
        check=True,
        timeout=30,
        capture_output=True,
    )
    return "/" + str(path.relative_to("static"))


@pytest.mark.asyncio
async def test_upload_remaps_identity_and_mixed_replaceable_slots(uploaded_trend):
    body, request, create = uploaded_trend
    body.update(
        identity_image_index=2,
        fixed_image_indices=[1],
        replaceable_image_indices=[3],
        prompt_text="@Image2 wears @Image1 with @Image3 and follows @Video1 to @Audio2.",
        video_urls=[
            add_typed_upload("video", "motion.mp4", b"0000ftypisom" + b"video")
        ],
        audio_urls=[
            add_typed_upload("audio", "fixed.mp3", b"ID3fixed"),
            add_typed_upload("audio", "own.mp3", b"ID3replaceable"),
        ],
        replaceable_video_indices=[1],
        fixed_audio_indices=[1],
        replaceable_audio_indices=[2],
    )
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    kwargs = create.await_args.kwargs
    settings = kwargs["generation_settings"]
    assert settings["reference_count"] == 4
    assert [(s["media_type"], s["position"]) for s in settings["reference_slots"]] == [
        ("image", 1),
        ("image", 3),
        ("video", 1),
        ("audio", 2),
    ]
    assert [
        (a["media_type"], a["position"]) for a in kwargs["trend_reference_assets"]
    ] == [("image", 2), ("audio", 1)]
    assert "@Image1 wears @Image2 with @Image3" in kwargs["prompt_text"]
    assert "refs/" not in json.dumps(kwargs)


@pytest.mark.asyncio
async def test_upload_retries_reuse_saved_recipe(uploaded_trend, monkeypatch):
    body, request, create = uploaded_trend
    saved = []

    async def lookup(_fingerprint, *, author_id):
        return saved[0] if saved else None

    async def save(**kwargs):
        row = {"id": 77, **kwargs, "status": "pending"}
        saved.append(row)
        return row

    async def approve(_prompt_id):
        saved[0]["status"] = "approved"
        return saved[0]

    monkeypatch.setattr(api, "get_active_seedance_trend_by_upload_fingerprint", lookup)
    create.side_effect = save
    monkeypatch.setattr(api, "approve_prompt", approve)
    first, retry = await asyncio.gather(
        *[
            api.miniapp_admin_publish_seedance_upload_trend(request(body))
            for _ in range(2)
        ]
    )
    assert first.status == retry.status == 200
    assert json.loads(first.text) == json.loads(retry.text)
    assert create.await_count == 1
    assert "seedance_upload_fingerprint" not in first.text
    assert "refs/" not in first.text


@pytest.mark.asyncio
async def test_upload_preview_failure_never_creates_prompt(uploaded_trend):
    body, request, create = uploaded_trend
    api.persist_feed_result_urls.return_value = []
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_route_is_registered():
    from aiohttp import web

    app = web.Application()
    api.setup_seedance_trend_admin_routes(app, "/mini-app")
    routes = {route.resource.canonical: route.handler for route in app.router.routes()}
    assert unwrap(
        routes["/mini-app/api/admin/trends/seedance/publish-upload"]
    ) is unwrap(api.miniapp_admin_publish_seedance_upload_trend)
    assert unwrap(routes["/mini-app/api/admin/trends/seedance/publish"]) is unwrap(
        api.miniapp_admin_publish_seedance_trend
    )


@pytest.mark.asyncio
async def test_upload_accepts_real_month_partitioned_storage_layout(uploaded_trend):
    body, request, create = uploaded_trend
    for field in ("image_urls",):
        shifted = []
        for url in body[field]:
            old = Path("static" + url)
            new = old.parent / "202610" / old.name
            new.parent.mkdir(exist_ok=True)
            old.rename(new)
            shifted.append("/" + str(new.relative_to("static")))
        body[field] = shifted
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    create.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,media_type,count",
    [
        ("seedance_2", "image", 10),
        ("seedance_2", "video", 4),
        ("seedance_2", "audio", 4),
        ("seedance_2_5", "image", 31),
        ("seedance_2_5", "video", 11),
        ("seedance_2_5", "audio", 11),
    ],
)
async def test_upload_rejects_provider_reference_overflow(
    uploaded_trend, model, media_type, count
):
    body, request, create = uploaded_trend
    body["model"] = model
    body[f"{media_type}_urls"] = [
        f"/uploads/refs/{media_type}/9001/{i}.png" for i in range(count)
    ]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    assert "максимум" in json.loads(response.text)["error"]
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_upload_uses_generator_image_validation(uploaded_trend):
    body, request, create = uploaded_trend
    body["model"] = "seedance_2_5"
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    assert (
        create.await_args.kwargs["generation_settings"]["seedance25_resolution"]
        == "720p"
    )
    create.reset_mock()
    Image.new("RGB", (10, 10), "pink").save(Path("static" + body["image_urls"][0]))
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("replaceable", [False, True])
async def test_seedance25_upload_editing_stores_measured_duration(
    uploaded_trend, monkeypatch, replaceable
):
    from bot.handlers import seedance_25_fullstack as fullstack

    body, request, create = uploaded_trend
    video = add_typed_upload("video", "editing.mp4", b"0000ftypisomediting")
    body.update(
        model="seedance_2_5",
        seedance25_video_editing=True,
        duration=-1,
        aspect_ratio="adaptive",
        video_urls=[video],
        fixed_video_indices=[] if replaceable else [1],
        replaceable_video_indices=[1] if replaceable else [],
    )
    monkeypatch.setattr(fullstack, "_validate_seedance_sources", AsyncMock())
    monkeypatch.setattr(
        fullstack, "_validate_local_source", AsyncMock(return_value=11.2)
    )
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    settings = create.await_args.kwargs["generation_settings"]
    assert settings["duration"] == -1
    assert settings["ratio"] == "adaptive"
    assert settings["source_video_duration_seconds"] == 12
    if replaceable:
        assert settings["required_video_duration_seconds"] == 12
        assert all(
            a["media_type"] != "video"
            for a in create.await_args.kwargs["trend_reference_assets"]
        )
    else:
        assert "required_video_duration_seconds" not in settings


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [None, 3.9, 30.1])
async def test_seedance25_upload_editing_rejects_invalid_duration(
    uploaded_trend, monkeypatch, duration
):
    from bot.handlers import seedance_25_fullstack as fullstack

    body, request, create = uploaded_trend
    body.update(
        model="seedance_2_5",
        seedance25_video_editing=True,
        duration=-1,
        aspect_ratio="adaptive",
        video_urls=[add_typed_upload("video", "editing.mp4", b"0000ftypisomediting")],
        fixed_video_indices=[1],
    )
    monkeypatch.setattr(fullstack, "_validate_seedance_sources", AsyncMock())
    monkeypatch.setattr(
        fullstack, "_validate_local_source", AsyncMock(return_value=duration)
    )
    persist = AsyncMock()
    monkeypatch.setattr(api, "_persist_recipe_assets", persist)
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    persist.assert_not_awaited()
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_seedance25_upload_rejects_auto_nonediting(uploaded_trend):
    body, request, create = uploaded_trend
    body.update(model="seedance_2_5", duration=-1)
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_real_sqlite_persistence_dedupe_and_public_privacy(
    uploaded_trend, monkeypatch
):
    from bot import database, miniapp
    from bot.services import feed_persist
    from bot.trend_api import trusted_trend_run

    body, request, _create = uploaded_trend
    user = await database.get_or_create_user(9001)
    monkeypatch.setattr(
        miniapp, "_get_user_context", AsyncMock(return_value=(9001, {"user": user}))
    )
    for name in (
        "create_prompt",
        "approve_prompt",
        "get_active_seedance_trend_by_upload_fingerprint",
    ):
        monkeypatch.setattr(api, name, getattr(database, name))
    monkeypatch.setattr(
        api, "persist_feed_result_urls", feed_persist.persist_feed_result_urls
    )
    first = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert first.status == 200, first.text
    second = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert second.status == 200, second.text
    public = json.loads(first.text)["prompt"]
    assert json.loads(second.text)["prompt"]["id"] == public["id"]
    assert public["prompt_text"] == ""
    assert public["model"] is None
    assert "seedance_upload_fingerprint" not in first.text
    assert "refs/" not in first.text
    saved = await database.get_prompt_by_id(public["id"])
    assert saved.get("source_generation_id") is None
    assert saved["status"] == "approved"
    assets = await database.list_trend_reference_assets(public["id"])
    assert len(assets) == 1
    assert "trend-assets/image/" in assets[0]["file_url"]
    from urllib.parse import urlsplit

    preview = Path("static" + urlsplit(saved["preview_url"]).path)
    assert preview.is_file()
    assert "/uploads/feed/" in saved["preview_url"]
    assert preview.read_bytes() == Path("static" + body["preview_url"]).read_bytes()
    fingerprint = saved["generation_settings"]["seedance_upload_fingerprint"]
    assert (
        await database.get_active_seedance_trend_by_upload_fingerprint(
            fingerprint, author_id=user.id + 1
        )
        is None
    )
    trend = trusted_trend_run(
        saved,
        ["/uploads/refs/image/222/face.png"],
        {"age": "31"},
        template_assets=assets,
        reference_inputs=[
            {
                "media_type": "image",
                "position": 1,
                "url": "/uploads/refs/image/222/face.png",
            }
        ],
    )
    assert trend.provider_image_urls == (
        "/uploads/refs/image/222/face.png",
        assets[0]["file_url"],
    )
    assert "face.png" not in trend.prompt
    assert "Возраст: 31" in trend.prompt
    await database.deactivate_prompt(public["id"], author_id=user.id)
    assert (
        await database.get_active_seedance_trend_by_upload_fingerprint(
            fingerprint, author_id=user.id
        )
        is None
    )


@pytest.mark.asyncio
async def test_upload_approval_failure_can_retry_without_duplicate(
    uploaded_trend, monkeypatch
):
    from bot import database, miniapp

    body, request, _create = uploaded_trend
    user = await database.get_or_create_user(9001)
    monkeypatch.setattr(
        miniapp, "_get_user_context", AsyncMock(return_value=(9001, {"user": user}))
    )
    monkeypatch.setattr(api, "create_prompt", database.create_prompt)
    monkeypatch.setattr(
        api,
        "get_active_seedance_trend_by_upload_fingerprint",
        database.get_active_seedance_trend_by_upload_fingerprint,
    )
    monkeypatch.setattr(api, "approve_prompt", AsyncMock(return_value=None))
    first = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert first.status == 500
    monkeypatch.setattr(api, "approve_prompt", database.approve_prompt)
    second = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert second.status == 200
    assert len(await database.get_author_prompts(user.id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,extension,data",
    [
        ("video", "mp4", b"0000ftypisomnot-a-video"),
        ("audio", "mp3", b"ID3not-audio"),
    ],
)
async def test_upload_rejects_header_only_invalid_media(
    uploaded_trend, kind, extension, data
):
    body, request, create = uploaded_trend
    path = Path(f"static/uploads/refs/{kind}/9001/forged.{extension}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    body[f"{kind}_urls"] = ["/" + str(path.relative_to("static"))]
    body[f"fixed_{kind}_indices"] = [1]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_rejects_audio_only_mp4_as_video(uploaded_trend):
    body, request, create = uploaded_trend
    audio = add_typed_upload("audio", "audio-only.m4a", b"synthetic")
    path = Path("static/uploads/refs/video/9001/audio-only.mp4")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Path("static" + audio).read_bytes())
    body["video_urls"] = ["/" + str(path.relative_to("static"))]
    body["fixed_video_indices"] = [1]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()


def add_seedance2_video(name, duration, color="purple", size_bytes=None):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe required for synthetic playable media")
    path = Path(f"static/uploads/refs/video/9001/{name}.mp4")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x64:r=24:d={duration}",
            "-c:v",
            "mpeg4",
            "-y",
            str(path),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    if size_bytes is not None:
        with path.open("r+b") as stream:
            stream.truncate(size_bytes)
    return "/" + str(path.relative_to("static"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fixed", "replaceable"])
@pytest.mark.parametrize("durations", [(1.5,), (16,), (10, 10)])
async def test_seedance2_upload_rejects_invalid_included_video_durations(
    uploaded_trend, mode, durations
):
    body, request, create = uploaded_trend
    body["video_urls"] = [
        add_seedance2_video(f"duration-{index}", duration, ("purple", "yellow")[index])
        for index, duration in enumerate(durations)
    ]
    body[f"{mode}_video_indices"] = list(range(1, len(durations) + 1))
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()
    api.persist_feed_result_urls.assert_not_awaited()
    assert not Path("static/uploads/trend-assets").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fixed", "replaceable"])
async def test_seedance2_upload_rejects_included_video_over_model_byte_limit(
    uploaded_trend, mode
):
    from bot.handlers.seedance_multimodal_compat import SEEDANCE_MAX_VIDEO_BYTES

    body, request, create = uploaded_trend
    body["video_urls"] = [
        add_seedance2_video("oversize", 5, size_bytes=SEEDANCE_MAX_VIDEO_BYTES + 1)
    ]
    body[f"{mode}_video_indices"] = [1]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400, response.text
    create.assert_not_awaited()
    api.persist_feed_result_urls.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("durations", [(2,), (15,), (7, 8)])
async def test_seedance2_upload_accepts_video_duration_boundaries(
    uploaded_trend, durations
):
    body, request, create = uploaded_trend
    body["video_urls"] = [
        add_seedance2_video(f"allowed-{index}", duration, ("purple", "yellow")[index])
        for index, duration in enumerate(durations)
    ]
    body["fixed_video_indices"] = list(range(1, len(durations) + 1))
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    assert len(create.await_args.kwargs["trend_reference_assets"]) == 1 + len(durations)


@pytest.mark.asyncio
async def test_seedance2_upload_does_not_apply_provider_duration_to_excluded_video(
    uploaded_trend,
):
    body, request, create = uploaded_trend
    body["video_urls"] = [add_seedance2_video("excluded-long", 16)]
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    assert all(
        asset["media_type"] != "video"
        for asset in create.await_args.kwargs["trend_reference_assets"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
@pytest.mark.parametrize("excluded_extra", [False, True])
async def test_single_identity_upload_roundtrips_to_repeat(
    uploaded_trend, monkeypatch, model, excluded_extra
):
    from bot.handlers import seedance_25_fullstack as fullstack
    from bot.trend_api import trusted_trend_run

    body, request, create = uploaded_trend
    body.update(
        model=model,
        image_urls=body["image_urls"][:2 if excluded_extra else 1],
        fixed_image_indices=[],
        prompt_text="Animate @Image1",
        user_fields=[],
    )
    validate = AsyncMock()
    monkeypatch.setattr(fullstack, "_validate_seedance_sources", validate)
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 200, response.text
    saved = json.loads(json.dumps(create.await_args.kwargs))
    settings = saved["generation_settings"]
    assert settings["reference_plan_version"] == 2
    assert settings["reference_count"] == 1
    assert settings["reference_slots"] == [
        {"media_type": "image", "position": 1, "label": "ВАШЕ ЛИЦО"}
    ]
    assert saved["trend_reference_assets"] == []
    assert all(settings[f"fixed_{kind}_reference_count"] == 0
               for kind in ("image", "video", "audio"))
    assert "face.png" not in json.dumps(saved)
    assert "dress.png" not in json.dumps(saved)
    assert "refs/" not in response.text
    user_photo = "https://test.example/current-user.png"
    run = trusted_trend_run(
        {"id": 77, "status": "approved", **saved},
        (user_photo,),
        template_assets=saved["trend_reference_assets"],
        reference_inputs=({"media_type": "image", "position": 1, "url": user_photo},),
    )
    assert run.model == model
    assert run.provider_image_urls == (user_photo,)
    assert run.provider_video_urls == ()
    assert run.provider_audio_urls == ()
    assert run.template_image_urls == ()
    assert run.template_video_urls == ()
    assert run.template_audio_urls == ()
    if model == "seedance_2_5":
        validate.assert_awaited_once()
        assert len(validate.await_args.kwargs["image_urls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [0, None])
async def test_single_photo_upload_still_requires_identity(uploaded_trend, identity):
    body, request, create = uploaded_trend
    body.update(image_urls=body["image_urls"][:1], fixed_image_indices=[],
                prompt_text="Animate @Image1", identity_image_index=identity)
    response = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert response.status == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
async def test_single_identity_sqlite_publication_and_repeat(
    uploaded_trend, monkeypatch, model
):
    from bot import database, miniapp
    from bot.handlers import seedance_25_fullstack as fullstack
    from bot.trend_api import trusted_trend_run

    body, request, _create = uploaded_trend
    body.update(model=model, image_urls=body["image_urls"][:1],
                fixed_image_indices=[], prompt_text="Animate @Image1")
    user = await database.get_or_create_user(9001)
    monkeypatch.setattr(
        miniapp, "_get_user_context", AsyncMock(return_value=(9001, {"user": user}))
    )
    for name in ("create_prompt", "approve_prompt",
                 "get_active_seedance_trend_by_upload_fingerprint"):
        monkeypatch.setattr(api, name, getattr(database, name))
    monkeypatch.setattr(fullstack, "_validate_seedance_sources", AsyncMock())
    first = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert first.status == 200, first.text
    retry = await api.miniapp_admin_publish_seedance_upload_trend(request(body))
    assert retry.status == 200, retry.text
    public = json.loads(first.text)["prompt"]
    assert json.loads(retry.text)["prompt"]["id"] == public["id"]
    assert public["prompt_text"] == ""
    assert public["model"] is None
    assert "refs/" not in first.text
    saved = await database.get_prompt_by_id(public["id"])
    assets = await database.list_trend_reference_assets(public["id"])
    assert assets == []
    assert saved["generation_settings"]["reference_count"] == 1
    assert len(await database.get_author_prompts(user.id)) == 1
    user_photo = "/uploads/refs/image/222/current-user.png"
    run = trusted_trend_run(
        saved, (user_photo,), {"age": "31"}, template_assets=assets,
        reference_inputs=({"media_type": "image", "position": 1, "url": user_photo},),
    )
    assert run.provider_image_urls == (user_photo,)
    assert run.provider_video_urls == run.provider_audio_urls == ()
    assert "Возраст: 31" in run.prompt
    assert "face.png" not in run.prompt
