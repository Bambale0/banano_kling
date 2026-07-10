import logging
from typing import Optional

import aiohttp
from vkbottle.api import ABCAPI

try:
    from vkbottle.types import PhotosPhoto
except Exception:
    from vkbottle_types.objects import PhotosPhoto

logger = logging.getLogger(__name__)


async def upload_photo_to_messages(
    api: ABCAPI, peer_id: int, image_bytes: bytes, filename: str = "photo.jpg"
) -> Optional[str]:
    """
    Загружает фото в приватный альбом сообщений для peer_id и возвращает attachment string.
    Использует photos.getMessagesUploadServer + upload + saveMessagesPhoto.
    """
    try:
        # Получаем upload server
        upload_server = await api.photos.get_messages_upload_server(peer_id=peer_id)
        logger.debug(f"get_messages_upload_server returned: {upload_server}")

        # Upload
        form = aiohttp.FormData()
        form.add_field(
            "photo", image_bytes, filename=filename, content_type="image/jpeg"
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_server.upload_url, data=form) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(
                        f"Upload to VK upload_url failed: status={resp.status} text={text}"
                    )
                    raise ValueError(f"Upload failed: {resp.status}")
                try:
                    upload_data = await resp.json()
                except Exception:
                    logger.debug(f"Upload response text (non-json): {text}")
                    raise

        logger.debug(f"Upload server returned data: {upload_data}")

        # Save
        photos = await api.photos.save_messages_photo(
            photo=upload_data["photo"],
            server=upload_data["server"],
            hash=upload_data["hash"],
        )

        logger.debug(f"photos.save_messages_photo returned: {photos}")
        if not photos:
            logger.error("save_messages_photo returned empty list")
            return None

        photo = photos[0]
        attachment = f"photo{photo.owner_id}_{photo.id}"
        # include access_key if present
        if getattr(photo, "access_key", None):
            attachment = f"photo{photo.owner_id}_{photo.id}_{photo.access_key}"
        logger.info(f"Uploaded photo attachment: {attachment}")
        return attachment

    except Exception as e:
        logger.exception(f"Upload photo error: {e}")
        return None
