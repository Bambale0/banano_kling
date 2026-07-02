import base64
import hashlib
import hmac
import json
import logging
from typing import Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


def normalize_kie_url(url: str) -> str:
    """Превращает относительный URL в абсолютный для Kie.ai.
    Kie не умеет ходить по относительным путям."""
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return url
    from bot.config import config

    host = config.WEBHOOK_HOST.rstrip("/")
    return f"{host}{url}"


class KieMarketError(Exception):
    """Ошибка KIE Market API."""
    def __init__(self, response: dict, message: str = "KIE Market API error"):
        self.response = response
        self.code = response.get("code", 0)
        self.msg = response.get("msg", str(response))
        super().__init__(f"{message}: code={self.code} msg={self.msg}")


class KieMarketService:
    """Общий адаптер для KIE Market моделей (Nano Banana 2 Lite и др.).
    Все market-модели идут через единый POST /api/v1/jobs/createTask."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.kie.ai"
        self.upload_base_url = "https://kieai.redpandaai.co"
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _post(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(
                f"{self.base_url}{endpoint}", headers=headers, json=payload
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error = await resp.text()
                logger.error(
                    "KieMarket POST %s failed: %s - %s", endpoint, resp.status, error
                )
                return None
        except Exception as exc:
            logger.exception("KieMarket POST error: %s", exc)
            return None

    async def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with session.get(
                f"{self.base_url}{endpoint}", headers=headers, params=params
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                error = await resp.text()
                if resp.status != 404:
                    logger.warning(
                        "KieMarket GET %s failed: %s - %s", endpoint, resp.status, error
                    )
                return None
        except Exception as exc:
            logger.exception("KieMarket GET error: %s", exc)
            return None

    # ─── Task creation ───────────────────────────────────────────────────────

    async def create_task(
        self,
        model: str,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        aspect_ratio: str = "auto",
        callback_url: Optional[str] = None,
    ) -> Optional[str]:
        """Создать задачу для любой KIE Market модели.

        Args:
            model: Имя модели в KIE (например "nano-banana-2-lite").
            prompt: Текстовый промпт.
            image_urls: Опциональные URL референсных изображений (до 10).
            aspect_ratio: Соотношение сторон.
            callback_url: URL для webhook-уведомления.

        Returns:
            task_id или None при ошибке.
        """
        payload: Dict = {
            "model": model,
            "input": {
                "prompt": prompt,
                "image_urls": [
                    normalize_kie_url(url) for url in (image_urls or [])
                ],
                "aspect_ratio": aspect_ratio,
            },
        }
        if callback_url:
            payload["callBackUrl"] = callback_url

        resp = await self._post("/api/v1/jobs/createTask", payload)
        if not resp or not isinstance(resp, dict):
            logger.error("KieMarket create_task failed, resp: %s", resp)
            return None

        # Проверка code != 200
        if resp.get("code") != 200:
            logger.error(
                "KieMarket create_task rejected: code=%s msg=%s",
                resp.get("code"), resp.get("msg"),
            )
            return None

        data = resp.get("data")
        if not isinstance(data, dict):
            logger.error("KieMarket invalid data: %s (full resp: %s)", data, resp)
            return None

        task_id = data.get("taskId")
        if not task_id:
            logger.error("No taskId in response: %s", resp)
        return task_id

    # ─── Task status ─────────────────────────────────────────────────────────

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус и результат задачи.
        Ответ: data.state (waiting/queuing/generating/success/fail),
               data.resultJson, data.failCode, data.failMsg."""
        resp = await self._get(
            "/api/v1/jobs/recordInfo", params={"taskId": task_id}
        )
        if not resp or not isinstance(resp, dict):
            return None
        data = resp.get("data")
        if not isinstance(data, dict):
            logger.warning("KieMarket status invalid data: %s", data)
            return None
        return data

    async def wait_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        delay: float = 5.0,
    ) -> Optional[Dict]:
        """Polling-ожидание завершения задачи.

        Args:
            task_id: ID задачи в KIE.
            max_attempts: Максимальное количество попыток (5 мин при delay=5).
            delay: Пауза между попытками в секундах.

        Returns:
            task_data из get_task_status() при success, None при fail/timeout.
        """
        import asyncio

        consecutive_failures = 0
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    logger.error(
                        "KieMarket task %s not found after %s consecutive errors",
                        task_id,
                        consecutive_failures,
                    )
                    return None
                await asyncio.sleep(delay)
                continue
            consecutive_failures = 0
            task_state = status.get("state", "").lower()
            if task_state == "success":
                return status
            elif task_state == "fail":
                logger.error(
                    "KieMarket task %s failed: %s",
                    task_id,
                    status.get("failMsg", "Unknown"),
                )
                return None
            await asyncio.sleep(delay)
        logger.warning(
            "KieMarket task %s timeout after %s attempts", task_id, max_attempts
        )
        return None

    # ─── Result parser ───────────────────────────────────────────────────────

    def parse_result_urls(self, task_data: Dict) -> List[str]:
        """Извлечь URL результатов из task_data (data из recordInfo или webhook)."""
        result_json_str = task_data.get("resultJson", "{}")
        try:
            result_json = json.loads(result_json_str)
            urls = result_json.get("resultUrls", [])
            return urls if isinstance(urls, list) else []
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    # ─── Generate image (shortcut) ────────────────────────────────────────────

    async def generate_image(
        self,
        model: str,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        aspect_ratio: str = "auto",
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Создать задачу генерации и вернуть task_id в dict."""
        task_id = await self.create_task(
            model=model,
            prompt=prompt,
            image_urls=image_urls,
            aspect_ratio=aspect_ratio,
            callback_url=callback_url,
        )
        if task_id:
            return {"task_id": task_id}
        return None

    async def generate_nano_banana_2_lite(
        self,
        prompt: str,
        image_urls: Optional[List[str]] = None,
        aspect_ratio: str = "auto",
        callback_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Сокращение для Nano Banana 2 Lite.
        Сначала пытается создать задачу, затем ждёт результат через polling.
        Если указан callback_url, возвращает task_id для webhook-режима.
        """
        task_id = await self.create_task(
            model="nano-banana-2-lite",
            prompt=prompt,
            image_urls=image_urls,
            aspect_ratio=aspect_ratio,
            callback_url=callback_url,
        )
        if not task_id:
            return None

        # Если указан callback_url — возвращаем task_id, результат придёт через webhook
        if callback_url:
            return {"task_id": task_id}

        # Иначе ждём результат через polling (до 5 минут)
        import aiohttp

        task_data = await self.wait_for_completion(task_id, max_attempts=60, delay=5.0)
        if not task_data:
            logger.error(
                "Nano Banana 2 Lite task %s failed or timed out", task_id
            )
            return {"error": True, "message": "Task failed or timed out"}

        # Извлекаем URL результата
        result_urls = self.parse_result_urls(task_data)
        if not result_urls:
            logger.error(
                "Nano Banana 2 Lite task %s: no result URLs in data: %s",
                task_id,
                task_data,
            )
            return {"error": True, "message": "No result from API"}

        # Скачиваем изображение
        session = await self._get_session()
        try:
            async with session.get(result_urls[0], timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    logger.error(
                        "Nano Banana 2 Lite download failed: status %s",
                        resp.status,
                    )
                    return {"error": True, "message": f"Download failed: status {resp.status}"}
                image_bytes = await resp.read()
                return image_bytes
        except Exception as exc:
            logger.exception("Nano Banana 2 Lite download error: %s", exc)
            return {"error": True, "message": str(exc)}

    # ─── File upload ──────────────────────────────────────────────────────────

    async def upload_file_base64(self, base64_data: str, file_name: str = "image.png") -> Optional[str]:
        """Загрузить файл через Base64 upload. Для маленьких изображений."""
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "file": base64_data,
            "fileName": file_name,
            "uploadPath": "images/telegram",
        }
        try:
            async with session.post(
                f"{self.upload_base_url}/api/file-base64-upload",
                headers=headers,
                json=payload,
            ) as resp:
                data = await resp.json()
                if data.get("success") and data.get("data", {}).get("downloadUrl"):
                    return data["data"]["downloadUrl"]
                logger.error("KieMarket base64 upload failed: %s", data)
                return None
        except Exception as exc:
            logger.exception("KieMarket base64 upload error: %s", exc)
            return None

    async def upload_file_stream(
        self,
        file_bytes: bytes,
        file_name: str = "image.png",
        upload_path: str = "images/telegram",
    ) -> Optional[str]:
        """Загрузить файл через Stream upload. Основной метод для Telegram-файлов."""
        session = await self._get_session()
        form = aiohttp.FormData()
        form.add_field(
            "file",
            file_bytes,
            filename=file_name,
            content_type="image/png",
        )
        form.add_field("uploadPath", upload_path)
        form.add_field("fileName", file_name)

        try:
            async with session.post(
                f"{self.upload_base_url}/api/file-stream-upload",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form,
            ) as resp:
                data = await resp.json()
                if data.get("success") and data.get("data", {}).get("downloadUrl"):
                    return data["data"]["downloadUrl"]
                logger.error("KieMarket stream upload failed: %s", data)
                return None
        except Exception as exc:
            logger.exception("KieMarket stream upload error: %s", exc)
            return None

    async def upload_file_url(self, file_url: str) -> Optional[str]:
        """Загрузить файл по URL (если файл уже доступен публично)."""
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "url": file_url,
            "uploadPath": "images/telegram",
        }
        try:
            async with session.post(
                f"{self.upload_base_url}/api/file-url-upload",
                headers=headers,
                json=payload,
            ) as resp:
                data = await resp.json()
                if data.get("success") and data.get("data", {}).get("downloadUrl"):
                    return data["data"]["downloadUrl"]
                logger.error("KieMarket URL upload failed: %s", data)
                return None
        except Exception as exc:
            logger.exception("KieMarket URL upload error: %s", exc)
            return None

    # ─── Credits ──────────────────────────────────────────────────────────────

    async def get_remaining_credits(self) -> Optional[int]:
        """Получить оставшиеся кредиты аккаунта KIE."""
        resp = await self._get("/api/v1/chat/credit")
        if resp and isinstance(resp, dict) and resp.get("code") == 200:
            data = resp.get("data")
            if isinstance(data, (int, float)):
                return int(data)
        return None

    # ─── Download URL ─────────────────────────────────────────────────────────

    async def get_download_url(self, generated_url: str) -> Optional[str]:
        """Получить временную download-ссылку (20 мин) для сгенерированного KIE файла."""
        resp = await self._post(
            "/api/v1/common/download-url",
            {"url": generated_url},
        )
        if resp and isinstance(resp, dict) and resp.get("code") == 200:
            data = resp.get("data")
            if isinstance(data, str):
                return data
            if isinstance(data, dict):
                return data.get("url")
        return None

    # ─── Webhook signature verification ──────────────────────────────────────

    def verify_webhook_signature(
        self,
        payload: dict,
        headers,
        webhook_hmac_key: str,
    ) -> bool:
        """Проверить HMAC-SHA256 подпись KIE webhook.
        KIE подписывает: base64(HMAC-SHA256(taskId + "." + timestamp, key))
        Заголовки: X-Webhook-Timestamp, X-Webhook-Signature."""
        timestamp = headers.get("X-Webhook-Timestamp")
        signature = headers.get("X-Webhook-Signature")

        task_id = payload.get("taskId") or payload.get("data", {}).get("taskId")

        if not timestamp or not signature or not task_id:
            return False

        message = f"{task_id}.{timestamp}".encode()
        secret = webhook_hmac_key.encode()

        digest = hmac.new(secret, message, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()

        return hmac.compare_digest(expected, signature)

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


from bot.config import config

kie_market_service = KieMarketService(api_key=config.KIE_AI_API_KEY)