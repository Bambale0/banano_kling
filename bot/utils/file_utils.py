import os
import uuid
from datetime import datetime
from typing import Optional

from bot.config import config


def save_uploaded_file(file_bytes: bytes, file_ext: str = "png") -> Optional[str]:
    """Сохраняет загруженный файл в static/uploads и возвращает публичный URL."""

    try:
        date_str = datetime.now().strftime("%Y%m%d")
        upload_dir = os.path.join("static", "uploads", date_str)
        os.makedirs(upload_dir, exist_ok=True)

        file_id = str(uuid.uuid4())[:8]
        filename = f"{file_id}.{file_ext}"
        filepath = os.path.join(upload_dir, filename)

        with open(filepath, "wb") as f:
            f.write(file_bytes)

        base_url = config.static_base_url.rstrip("/")
        public_url = f"{base_url}/uploads/{date_str}/{filename}"
        return public_url
    except Exception as e:
        from logging import getLogger

        logger = getLogger(__name__)
        logger.exception(f"Error saving uploaded file: {e}")
        return None
