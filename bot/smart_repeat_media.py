"""Bounded inspection of owned local assets; provider rules stay in adapters."""
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

from bot.smart_repeat_contract import fail


async def inspect_asset(path: str, kind: str) -> dict:
    def inspect():
        local = Path(path)
        try:
            if kind == 'image':
                with Image.open(local) as image:
                    width, height = image.size
                    image.verify()
                media = {'width': width, 'height': height}
            else:
                completed = subprocess.run([
                    'ffprobe', '-protocol_whitelist', 'file,pipe', '-v', 'error',
                    '-show_streams', '-show_format', '-of', 'json', str(local),
                ], capture_output=True, timeout=10, check=True)
                parsed = json.loads(completed.stdout)
                streams = [stream for stream in parsed.get('streams', []) if stream.get('codec_type') == kind]
                if not streams:
                    fail('INVALID_ASSET', 'Тип файла не соответствует полю.', 400)
                media = {'duration_seconds': (parsed.get('format') or {}).get('duration')}
            digest = hashlib.sha256()
            with local.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            return {'sha256': digest.hexdigest(), 'size_bytes': local.stat().st_size, 'media': media}
        except (OSError, ValueError, subprocess.SubprocessError, Image.DecompressionBombError):
            fail('INVALID_ASSET', 'Файл не прошёл проверку. Загрузите другой файл.', 400)
    return await asyncio.to_thread(inspect)
