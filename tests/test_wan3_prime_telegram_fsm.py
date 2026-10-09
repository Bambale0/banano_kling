from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from bot.handlers import wan3_prime


@pytest.fixture(autouse=True)
def isolated_database():
    yield


class FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.state = state.state if hasattr(state, "state") else state

    async def get_state(self):
        return self.state


class FakeMessage:
    def __init__(self, *, user_id=101, text=None, photo=None, video=None, audio=None, voice=None, document=None):
        self.from_user = SimpleNamespace(id=user_id)
        self.bot = SimpleNamespace(id=777)
        self.text = text
        self.photo = photo or []
        self.video = video
        self.audio = audio
        self.voice = voice
        self.document = document
        self.answers = []
        self.edits = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeCallback:
    def __init__(self, data, *, user_id=101, message=None):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message or FakeMessage(user_id=user_id)
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


@dataclass
class FakeFile:
    file_id: str
    file_size: int = 1024
    file_name: str | None = None


class FakeRuntime:
    def __init__(self):
        self.stored = []
        self.imported = []
        self.quotes = []
        self.launches = []
        self.launch_status = "accepted"
        self.raise_launch = False

    async def store_telegram_wan3_prime_media(self, *, telegram_id, bot, file_id, filename, kind, declared_size):
        self.stored.append({
            "telegram_id": telegram_id,
            "bot": bot,
            "file_id": file_id,
            "filename": filename,
            "kind": kind,
            "declared_size": declared_size,
        })
        return {"url": f"https://owned.test/{kind}/{file_id}", "kind": kind, "filename": filename, "size": declared_size}

    async def import_telegram_wan3_prime_reference(self, *, telegram_id, kind, url):
        self.imported.append({"telegram_id": telegram_id, "kind": kind, "url": url})
        return {"url": f"https://owned.test/imported/{kind}/{len(self.imported)}", "kind": kind}

    async def quote_telegram_wan3_prime(self, *, telegram_id, client_request_id, recipe):
        self.quotes.append({"telegram_id": telegram_id, "client_request_id": client_request_id, "recipe": recipe})
        return {
            "quote_hash": f"quote-{len(self.quotes)}",
            "reserve_cost": 42,
            "source_video_duration_seconds": 3,
            "billing_duration_seconds": 11,
            "auto_duration": recipe.get("duration") == -1,
            "admin_free": False,
            "tariff_missing": False,
            "settlement_notice": "Auto резерв будет пересчитан после результата.",
        }

    async def launch_telegram_wan3_prime(self, *, telegram_id, client_request_id, idempotency_key, quote_hash, recipe):
        if self.raise_launch:
            raise RuntimeError("network")
        self.launches.append({
            "telegram_id": telegram_id,
            "client_request_id": client_request_id,
            "idempotency_key": idempotency_key,
            "quote_hash": quote_hash,
            "recipe": recipe,
        })
        return {
            "status": self.launch_status,
            "internal_task_id": "wan-internal-1",
            "provider_task_id": "provider-1" if self.launch_status == "accepted" else None,
            "reserve_cost": 42,
        }

    async def owner_telegram_wan3_prime_recipe(self, *, telegram_id, task_id):
        return {"recipe": {"scenario": "reference", "prompt": "", "reference_audio_urls": ["https://owned.test/audio/a.mp3"]}}


@pytest.fixture
def runtime(monkeypatch):
    fake = FakeRuntime()

    async def get_runtime():
        return fake

    monkeypatch.setattr(wan3_prime, "_runtime", get_runtime)
    return fake


async def open_mode(state, runtime, scenario):
    cb = FakeCallback("wan3_open")
    await wan3_prime.open_wan3_prime(cb, state)
    cb = FakeCallback(f"wan3_mode:{scenario}", message=cb.message)
    await wan3_prime.choose_wan3_mode(cb, state)
    return cb


async def set_prompt(state, text):
    await wan3_prime.ask_wan3_prompt(FakeCallback("wan3_prompt"), state)
    await wan3_prime.wan3_prompt(FakeMessage(text=text), state)


async def upload(state, kind, file_id, *, filename=None, size=1024, text=None):
    cb = FakeCallback(f"wan3_media:{kind}")
    await wan3_prime.ask_wan3_media(cb, state)
    current = await state.get_state()
    assert current
    if text:
        msg = FakeMessage(text=text)
    elif kind in {"first", "last", "image"}:
        msg = FakeMessage(photo=[FakeFile(file_id, size, filename)])
    elif kind in {"source_video", "video"}:
        msg = FakeMessage(video=FakeFile(file_id, size, filename or f"{file_id}.mp4"))
    elif kind == "audio":
        msg = FakeMessage(audio=FakeFile(file_id, size, filename or f"{file_id}.mp3"))
    elif kind == "file":
        msg = FakeMessage(document=FakeFile(file_id, size, filename or f"{file_id}.pdf"))
    else:
        msg = FakeMessage(text=text or "https://example.test/page")
    await wan3_prime.receive_wan3_media(msg, state)
    return msg


@pytest.mark.asyncio
async def test_edit_flow_uploads_video1_image_seed0_audiofalse_quote_confirm_actor(runtime):
    state = FakeState()
    await open_mode(state, runtime, "edit")
    await upload(state, "source_video", "source-video", filename="source.mp4")
    await upload(state, "image", "style-image")
    await set_prompt(state, "Поменять куртку на красную")

    await wan3_prime.ask_wan3_seed(FakeCallback("wan3_seed"), state)
    await wan3_prime.receive_wan3_seed(FakeMessage(text="0"), state)
    await wan3_prime.toggle_wan3_option(FakeCallback("wan3_toggle:audio"), state)
    await wan3_prime.quote_wan3_prime(FakeCallback("wan3_quote", user_id=505), state)
    await wan3_prime.confirm_wan3_prime(FakeCallback("wan3_confirm", user_id=505), state)

    recipe = runtime.launches[-1]["recipe"]
    assert runtime.launches[-1]["telegram_id"] == 505
    assert recipe["scenario"] == "edit"
    assert recipe["prompt"] == "Поменять куртку на красную"
    assert recipe["reference_video_urls"] == ["https://owned.test/video/source-video"]
    assert recipe["reference_image_urls"] == ["https://owned.test/image/style-image"]
    assert recipe["seed"] == 0
    assert recipe["audio"] is False
    assert recipe["resolution"] == "1080P"
    assert recipe["aspect_ratio"] == "adaptive"


@pytest.mark.asyncio
async def test_first_last_frames_reject_reference_without_mode_change_and_controls_exist(runtime):
    state = FakeState()
    cb = await open_mode(state, runtime, "first_last")
    keyboard_texts = [button.text for row in cb.message.edits[-1][1]["reply_markup"].inline_keyboard for button in row]
    assert "Первый кадр" in keyboard_texts
    assert "Последний кадр" in keyboard_texts
    assert "1080P" in keyboard_texts
    assert "Аудио вкл/выкл" in keyboard_texts

    await upload(state, "first", "first-frame")
    await upload(state, "last", "last-frame")
    blocked = FakeCallback("wan3_media:image")
    await wan3_prime.ask_wan3_media(blocked, state)

    data = wan3_prime.draft_from_state(await state.get_data())
    assert data.first_frame_url == "https://owned.test/image/first-frame"
    assert data.last_frame_url == "https://owned.test/image/last-frame"
    assert data.reference_image_urls == []
    assert blocked.answers[-1][1]["show_alert"] is True


@pytest.mark.asyncio
async def test_audio_only_reference_empty_prompt_quotes(runtime):
    state = FakeState()
    await open_mode(state, runtime, "reference")
    await upload(state, "audio", "voice", filename="voice.mp3")
    await set_prompt(state, "-")
    await wan3_prime.quote_wan3_prime(FakeCallback("wan3_quote"), state)

    assert runtime.quotes[-1]["recipe"]["prompt"] == ""
    assert runtime.quotes[-1]["recipe"]["reference_audio_urls"] == ["https://owned.test/audio/voice"]


@pytest.mark.asyncio
async def test_file_with_image_and_link_with_video_permitted_but_file_link_exclusive(runtime):
    state = FakeState()
    await open_mode(state, runtime, "file")
    await upload(state, "file", "doc", filename="brief.docx")
    await upload(state, "image", "image")
    data = wan3_prime.draft_from_state(await state.get_data())
    assert data.reference_file_urls == ["https://owned.test/file/doc"]
    assert data.reference_image_urls == ["https://owned.test/image/image"]

    cb = FakeCallback("wan3_media:link")
    await wan3_prime.ask_wan3_media(cb, state)
    assert "взаимоисключают" in cb.answers[-1][0]
    data = wan3_prime.draft_from_state(await state.get_data())
    assert data.reference_link_urls == []

    state = FakeState()
    await open_mode(state, runtime, "link")
    await upload(state, "link", "unused", text="https://example.test/page")
    await upload(state, "video", "clip", filename="clip.mov")
    data = wan3_prime.draft_from_state(await state.get_data())
    assert data.reference_link_urls == ["https://owned.test/imported/link/1"]
    assert data.reference_video_urls == ["https://owned.test/video/clip"]


@pytest.mark.asyncio
async def test_remove_middle_reference_preserves_order_and_overflow_rejected(runtime):
    state = FakeState()
    await open_mode(state, runtime, "reference")
    for index in range(3):
        await upload(state, "image", f"img-{index}")

    await wan3_prime.remove_wan3_media(FakeCallback("wan3_remove:image:1"), state)
    draft = wan3_prime.draft_from_state(await state.get_data())
    assert draft.reference_image_urls == [
        "https://owned.test/image/img-0",
        "https://owned.test/image/img-2",
    ]

    for index in range(8):
        await upload(state, "image", f"more-{index}")
    overflow = await upload(state, "image", "overflow")
    draft = wan3_prime.draft_from_state(await state.get_data())
    assert len(draft.reference_image_urls) == 10
    assert "максимум 10" in overflow.answers[-1][0]


@pytest.mark.asyncio
async def test_duration_resolution_ratio_preserved_and_invalid_inputs_descriptive(runtime):
    state = FakeState()
    await open_mode(state, runtime, "reference")
    await wan3_prime.set_wan3_option(FakeCallback("wan3_set:duration:-1"), state)
    await wan3_prime.set_wan3_option(FakeCallback("wan3_set:resolution:1080P"), state)
    await wan3_prime.set_wan3_option(FakeCallback("wan3_set:ratio:9:16"), state)

    await wan3_prime.ask_wan3_duration(FakeCallback("wan3_duration"), state)
    bad = FakeMessage(text="2.8")
    await wan3_prime.receive_wan3_duration(bad, state)
    assert "целым числом" in bad.answers[-1][0]

    await upload(state, "audio", "sound", filename="sound.mp3")
    await set_prompt(state, "-")
    await wan3_prime.quote_wan3_prime(FakeCallback("wan3_quote"), state)
    recipe = runtime.quotes[-1]["recipe"]
    assert recipe["duration"] == -1
    assert recipe["resolution"] == "1080P"
    assert recipe["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_duplicate_confirm_same_key_network_exception_preserves_key_newtask_changes(runtime):
    state = FakeState()
    await open_mode(state, runtime, "reference")
    await upload(state, "audio", "sound", filename="sound.mp3")
    await set_prompt(state, "-")
    await wan3_prime.quote_wan3_prime(FakeCallback("wan3_quote"), state)
    draft = wan3_prime.draft_from_state(await state.get_data())
    first_key = draft.idempotency_key

    runtime.raise_launch = True
    await wan3_prime.confirm_wan3_prime(FakeCallback("wan3_confirm"), state)
    assert not runtime.launches
    assert wan3_prime.draft_from_state(await state.get_data()).idempotency_key == first_key

    runtime.raise_launch = False
    await wan3_prime.confirm_wan3_prime(FakeCallback("wan3_confirm"), state)
    await wan3_prime.confirm_wan3_prime(FakeCallback("wan3_confirm"), state)
    assert [launch["idempotency_key"] for launch in runtime.launches] == [first_key, first_key]

    await wan3_prime.set_wan3_option(FakeCallback("wan3_set:ratio:1:1"), state)
    assert wan3_prime.draft_from_state(await state.get_data()).quote_hash is None
    stale = FakeCallback("wan3_confirm")
    await wan3_prime.confirm_wan3_prime(stale, state)
    assert "Сначала обновите" in stale.answers[-1][0]

    await wan3_prime.new_wan3_prime(FakeCallback("wan3_new"), state)
    assert wan3_prime.draft_from_state(await state.get_data()).idempotency_key != first_key


@pytest.mark.asyncio
async def test_unknown_status_message_honest_and_no_fake_balance_calls(runtime):
    state = FakeState()
    await open_mode(state, runtime, "reference")
    await upload(state, "audio", "sound", filename="sound.mp3")
    await set_prompt(state, "-")
    await wan3_prime.quote_wan3_prime(FakeCallback("wan3_quote"), state)
    runtime.launch_status = "unknown"
    cb = FakeCallback("wan3_confirm")
    await wan3_prime.confirm_wan3_prime(cb, state)

    text = cb.message.edits[-1][0]
    assert "Статус отправки неизвестен" in text
    assert "wan-internal-1" in text
    assert "Task ID" in text
    assert runtime.launches[-1]["telegram_id"] == 101
