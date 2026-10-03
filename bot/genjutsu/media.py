"""Private, bounded media storage and explicit source preparation.

Only opaque server-generated storage keys are read. Network downloads are for
provider results, not arbitrary client URLs. DNS results and every redirect are
validated, and no provider credentials are ever sent to storage hosts.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import uuid4

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .contract import PipelineError, integer
from .provider import ProviderFailure, https_url


class PublicResolver(aiohttp.abc.AbstractResolver):
    def __init__(self):
        self._resolver = aiohttp.resolver.ThreadedResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if not literal.is_global:
                raise OSError('Non-public media address')
            return [{'hostname': host, 'host': str(literal), 'port': port,
                     'family': socket.AF_INET6 if literal.version == 6 else socket.AF_INET,
                     'proto': 0, 'flags': socket.AI_NUMERICHOST}]
        rows = await self._resolver.resolve(host, port, family)
        # Fail the complete answer, rather than picking a public entry next to
        # a private one. The connector uses these validated addresses directly.
        if not rows or any(not ipaddress.ip_address(row['host']).is_global for row in rows):
            raise OSError('Non-public media address')
        return rows

    async def close(self):
        await self._resolver.close()


async def _read_bounded(stream, limit: int) -> bytes:
    data = bytearray()
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return bytes(data)
        data.extend(chunk)
        if len(data) > limit:
            raise PipelineError('media_process_output_limit')


async def process(*argv: str, timeout: int) -> bytes:
    child = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _error, code = await asyncio.wait_for(asyncio.gather(
            _read_bounded(child.stdout, 131072), _read_bounded(child.stderr, 32768), child.wait()), timeout)
        if code:
            raise PipelineError('media_decode_failed')
        return out
    except BaseException:
        if child.returncode is None:
            child.kill()
        await child.wait()
        raise


class MediaStore:
    def __init__(self, root: Path, public_base: str, signing_key: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.public_base = public_base.rstrip('/')
        self.signing_key = signing_key.encode()
        self._media_condition = asyncio.Condition()
        self._media_active = 0

    @asynccontextmanager
    async def media_slot(self, limit: int):
        """Apply the live admin-configured media concurrency limit.

        Lowering the limit never cancels in-flight work: new jobs wait until
        the active count falls below the new value.
        """
        integer(limit, 1, 8, 'invalid_media_parallelism')
        async with self._media_condition:
            while self._media_active >= limit:
                await self._media_condition.wait()
            self._media_active += 1
        try:
            yield
        finally:
            async with self._media_condition:
                self._media_active -= 1
                self._media_condition.notify_all()

    @property
    def configured(self) -> bool:
        try:
            https_url(self.public_base)
            return len(self.signing_key) >= 32
        except ProviderFailure:
            return False

    def path(self, storage_key: str) -> Path:
        if not isinstance(storage_key, str) or not re.fullmatch(r'[a-f0-9]{32}\.(png|mp4|m4a|webm|tmp)', storage_key):
            raise PipelineError('invalid_storage_key')
        path = (self.root / storage_key).resolve()
        if path.parent != self.root:
            raise PipelineError('invalid_storage_key')
        return path

    def signature(self, purpose: str, identifier: str, expires: int) -> str:
        if len(self.signing_key) < 32:
            raise PipelineError('media_signing_not_configured', status=503)
        return hmac.new(self.signing_key, f'{purpose}:{identifier}:{expires}'.encode(), hashlib.sha256).hexdigest()

    def url(self, asset_id: str, *, ttl: int, now: int | None = None) -> str:
        if not self.configured:
            raise PipelineError('media_signing_not_configured', status=503)
        expires = (int(time.time()) if now is None else now) + ttl
        sig = self.signature('asset', asset_id, expires)
        return f'{self.public_base}/genjutsu/media/{asset_id}?' + urlencode({'expires': expires, 'signature': sig})

    def verify(self, asset_id: str, expires, signature, *, now: int | None = None) -> bool:
        try:
            expires = int(expires)
            now = int(time.time()) if now is None else now
            return (now < expires <= now + 604800 and isinstance(signature, str)
                    and hmac.compare_digest(signature, self.signature('asset', asset_id, expires)))
        except (TypeError, ValueError, PipelineError):
            return False

    def callback_url(self, step_id: str, attempt: str, *, ttl: int) -> str:
        expires = int(time.time()) + ttl
        identifier = f'{step_id}:{attempt}'
        return f'{self.public_base}/genjutsu/callback/{step_id}/{attempt}?' + urlencode({
            'expires': expires, 'signature': self.signature('callback', identifier, expires)})

    def verify_callback(self, step_id: str, attempt: str, expires, signature) -> bool:
        try:
            expires = int(expires)
            now = int(time.time())
            return (now < expires <= now + 604800 and isinstance(signature, str)
                and hmac.compare_digest(signature, self.signature('callback', f'{step_id}:{attempt}', expires)))
        except (TypeError, ValueError, PipelineError):
            return False

    async def probe(self, path: Path, settings: dict) -> dict:
        out = await process('ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-format_whitelist', 'mov,matroska,webm,wav,mp3,aac,ogg,flac',
            '-show_entries', 'format=duration,format_name:stream=codec_type,width,height,duration',
            '-of', 'json', str(path), timeout=min(settings['media_timeout_seconds'], 30))
        try:
            data = json.loads(out)
            streams = data['streams']
            videos = [s for s in streams if s.get('codec_type') == 'video']
            audios = [s for s in streams if s.get('codec_type') == 'audio']
            seconds = float(data['format']['duration'])
            if not math.isfinite(seconds) or seconds <= 0 or len(streams) > 10:
                raise ValueError('invalid metadata')
            duration_ms = math.ceil(seconds * 1000)
            if duration_ms > settings['max_source_duration_ms']:
                raise PipelineError('source_too_long')
            result = {'duration_ms': duration_ms, 'has_audio': bool(audios),
                      'container_format': data['format']['format_name']}
            if videos:
                width, height = int(videos[0]['width']), int(videos[0]['height'])
                if width <= 0 or height <= 0 or width * height > 16777216:
                    raise PipelineError('media_dimensions_limit')
                result.update(width=width, height=height)
            elif not audios:
                raise ValueError('missing stream')
            return result
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            if isinstance(exc, PipelineError):
                raise
            raise PipelineError('media_decode_failed') from exc

    @staticmethod
    def normalize_image(source: Path, destination: Path) -> dict:
        try:
            with Image.open(source) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP', 'HEIF', 'HEIC'}:
                    raise PipelineError('image_format_not_supported')
                if image.width * image.height > 25000000:
                    raise PipelineError('media_dimensions_limit')
                image = ImageOps.exif_transpose(image)
                image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
                image.save(destination, format='PNG')
                return {'width': image.width, 'height': image.height, 'mime': 'image/png'}
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise PipelineError('media_decode_failed') from exc

    async def ingest(self, chunks, kind: str, settings: dict) -> dict:
        if kind not in {'image', 'video', 'audio'}:
            raise PipelineError('unsupported_media_kind')
        limit = settings[f'upload_{kind}_bytes']
        temp, output = self.path(uuid4().hex + '.tmp'), None
        try:
            async with asyncio.timeout(settings['media_timeout_seconds']):
                size = 0
                with temp.open('xb') as handle:
                    os.chmod(temp, 0o600)
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > limit:
                            raise PipelineError('media_too_large', status=413)
                        handle.write(chunk)
                if not size:
                    raise PipelineError('empty_file')
                async with self.media_slot(settings['media_parallelism']):
                    if kind == 'image':
                        output = self.path(uuid4().hex + '.png')
                        metadata = await asyncio.to_thread(self.normalize_image, temp, output)
                    else:
                        metadata = await self.probe(temp, settings)
                        if kind == 'video' and 'width' not in metadata:
                            raise PipelineError('video_required')
                        if kind == 'audio' and 'width' in metadata:
                            raise PipelineError('audio_required')
                        output = self.path(uuid4().hex + ('.mp4' if kind == 'video' else '.m4a'))
                        if kind == 'video':
                            await process('ffmpeg', '-v', 'error', '-nostdin', '-threads', '1',
                                '-protocol_whitelist', 'file,pipe', '-i', str(temp),
                                '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
                                '-c:v', 'libx264', '-threads', '1', '-preset', 'fast', '-crf', '20',
                                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart',
                                '-fs', str(limit), '-y', str(output), timeout=settings['media_timeout_seconds'])
                        else:
                            await process('ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
                                '-i', str(temp), '-map', '0:a:0', '-c:a', 'aac', '-fs', str(limit),
                                '-y', str(output), timeout=settings['media_timeout_seconds'])
                        actual = await self.probe(output, settings)
                        if abs(actual['duration_ms'] - metadata['duration_ms']) > 250:
                            raise PipelineError('normalization_duration_changed')
                        metadata = {**actual, 'mime': 'video/mp4' if kind == 'video' else 'audio/mp4'}
                if output.stat().st_size >= limit:
                    raise PipelineError('media_too_large', status=413)
                os.chmod(output, 0o600)
                metadata.update(storage_key=output.name, size_bytes=output.stat().st_size,
                                sha256=await asyncio.to_thread(self._digest, output))
                return metadata
        except TimeoutError as exc:
            if output:
                output.unlink(missing_ok=True)
            raise PipelineError('media_timeout', status=408) from exc
        except BaseException:
            if output:
                output.unlink(missing_ok=True)
            raise
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _digest(path: Path) -> str:
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()

    async def trim(self, key: str, start_ms: int, end_ms: int, settings: dict) -> dict:
        source = self.path(key)
        metadata = await self.probe(source, settings)
        integer(start_ms, 0, metadata['duration_ms'], 'invalid_trim')
        integer(end_ms, start_ms + 1, metadata['duration_ms'], 'invalid_trim')
        if end_ms - start_ms > 30000:
            raise PipelineError('trim_too_long')
        target = self.path(uuid4().hex + '.mp4')
        try:
            async with self.media_slot(settings['media_parallelism']):
                await process('ffmpeg', '-v', 'error', '-nostdin', '-threads', '1', '-i', str(source),
                    '-ss', f'{start_ms / 1000:.3f}', '-t', f'{(end_ms-start_ms)/1000:.3f}',
                    '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-threads', '1',
                    '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-movflags', '+faststart', '-fs', str(settings['upload_video_bytes']),
                    '-y', str(target), timeout=settings['media_timeout_seconds'])
                result = await self.probe(target, settings)
            if abs(result['duration_ms'] - (end_ms - start_ms)) > 250:
                raise PipelineError('trim_duration_changed')
            if target.stat().st_size >= settings['upload_video_bytes']:
                raise PipelineError('media_too_large', status=413)
            os.chmod(target, 0o600)
            return {**result, 'mime': 'video/mp4', 'storage_key': target.name,
                    'size_bytes': target.stat().st_size, 'source_start_ms': start_ms,
                    'source_end_ms': end_ms, 'sha256': await asyncio.to_thread(self._digest, target)}
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    async def store_result(self, chunks, settings: dict) -> dict:
        """Persist original provider bytes; never silently recompress the result."""
        temporary = self.path(uuid4().hex + '.tmp')
        target = None
        try:
            size = 0
            async with asyncio.timeout(settings['media_timeout_seconds']):
                with temporary.open('xb') as output:
                    os.chmod(temporary, 0o600)
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > settings['result_max_bytes']:
                            raise PipelineError('media_too_large', status=413)
                        await asyncio.to_thread(output.write, chunk)
                if size == 0:
                    raise PipelineError('empty_media')
                async with self.media_slot(settings['media_parallelism']):
                    metadata = await self.probe(temporary, settings)
                if not metadata.get('width'):
                    raise PipelineError('video_required')
                formats = set(metadata['container_format'].split(','))
                extension = '.mp4' if 'mov' in formats else '.webm' if formats & {'webm', 'matroska'} else None
                if extension is None:
                    raise PipelineError('unsupported_result_container')
                target = self.path(uuid4().hex + extension)
                temporary.replace(target)
                return {**metadata, 'storage_key': target.name, 'size_bytes': size,
                        'mime': 'video/mp4' if extension == '.mp4' else 'video/webm',
                        'sha256': await asyncio.to_thread(self._digest, target)}
        except BaseException:
            if target:
                target.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    async def download_result(self, url: str, settings: dict) -> dict:
        current = https_url(url)
        # aiohttp bypasses its resolver for literal IPs: reject those here too.
        for _ in range(4):
            host = urlsplit(current).hostname
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                literal = None
            if literal and not literal.is_global:
                raise PipelineError('result_address_rejected')
            resolver = PublicResolver()
            connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
            try:
                async with (
                    aiohttp.ClientSession(
                        connector=connector,
                        timeout=aiohttp.ClientTimeout(total=settings['media_timeout_seconds']),
                        trust_env=False,
                    ) as session,
                    session.get(
                        current,
                        allow_redirects=False,
                        headers={'Accept': 'video/*'},
                    ) as response,
                ):
                        if response.status in (301, 302, 303, 307, 308):
                            current = https_url(urljoin(current, response.headers.get('Location', '')))
                            continue
                        if response.status != 200:
                            raise PipelineError('result_download_failed', status=502)
                        return await self.store_result(response.content.iter_chunked(262144), settings)
            finally:
                await resolver.close()
        raise PipelineError('result_redirect_limit')

    def discard(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    async def ensure_asset(self, asset: dict) -> None:
        path = self.path(asset['storage_key'])
        if not path.is_file() or path.stat().st_size != asset['size_bytes']:
            raise PipelineError('asset_file_unavailable', status=404)
        if asset.get('sha256') and await asyncio.to_thread(self._digest, path) != asset['sha256']:
            raise PipelineError('asset_integrity_failed', status=409)
