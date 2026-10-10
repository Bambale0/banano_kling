"""Real owned-image upload -> model validation -> quote. No external network."""
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from bot import database
from bot.config import config
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor, Wan3PrimeLifecycle
from bot.services.wan3_prime_storage import Wan3PrimeStorage


class Prices:
    def get_video_quality_costs(self, _model):
        return {'1080p': 2.0}


@pytest.mark.asyncio
async def test_completed_upload_is_a_valid_image_reference_and_completion_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, 'STATIC_BASE_URL', 'https://owned.example')
    user = await database.get_or_create_user(424242)
    actor = Wan3PrimeActor(user.id, 424242)
    raw = BytesIO()
    Image.new('RGB', (320, 240)).save(raw, format='PNG')
    payload = raw.getvalue()
    storage = Wan3PrimeStorage()
    upload = await storage.init_upload(actor, kind='image', filename='portrait.png', size=len(payload), content_type='image/png')
    await storage.save_chunk(actor, upload_id=upload['upload_id'], index=0, total=1, chunk=payload)
    completed = await storage.complete_upload(actor, upload_id=upload['upload_id'])
    runtime = Wan3PrimeLifecycle(preset_manager=Prices())
    quote = await runtime.quote(actor, {'scenario': 'reference', 'prompt': '', 'reference_image_urls': [completed['url']], 'duration': 5})
    assert quote.reserve_credits == 10
    assert completed['url'].startswith('https://owned.example/uploads/')
    repeated = await storage.complete_upload(actor, upload_id=upload['upload_id'])
    assert repeated['url'] == completed['url']
    assert len(list(Path('static/uploads/wan3_prime/references').rglob('*.png'))) == 1
