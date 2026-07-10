import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


async def download_media_bytes(attachment) -> Optional[bytes]:
    """Downloads media bytes from VK CDN. Handles photo/video/doc."""

    url = None

    # Log attachment structure for debug
    logger.debug("download_media_bytes attachment: %s", str(dir(attachment))[:500])

    att_type = getattr(attachment, "type", None)

    if att_type == "photo":
        photo = getattr(attachment, "photo", attachment)
        sizes = getattr(photo, "sizes", [])
        if sizes:
            # Prefer 'max' type
            max_url = next(
                (s.url for s in sizes if getattr(s, "type", "") == "max"), None
            )
            if max_url:
                url = max_url
            else:
                # Largest size
                max_size = max(
                    sizes,
                    key=lambda s: getattr(s, "height", 0) * getattr(s, "width", 0),
                )
                url = getattr(max_size, "url", None)
        else:
            url = getattr(photo, "url", None)

    elif att_type == "video":
        video = getattr(attachment, "video", attachment)
        # Prefer direct MP4 download links
        url = (
            getattr(video, "external_link_mp4", None)
            or getattr(video, "link_mp4", None)
            or getattr(video, "url", None)
            or getattr(video, "player", None)
        )  # fallback, but player is embed

    elif att_type == "doc":
        doc = getattr(attachment, "doc", attachment)
        url = getattr(doc, "url", None)
        logger.info(
            "Doc download: url=%s ext=%s size=%s",
            url,
            getattr(doc, "ext", "unknown"),
            getattr(doc, "size", "unknown"),
        )

    if not url:
        logger.warning("No media URL found in attachment: type=%s", att_type)
        return None

    logger.info("Downloading from URL: %s", url)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    logger.info("Downloaded %d bytes from %s", len(data), url)
                    return data
                else:
                    logger.warning("Download failed: %s %s", resp.status, url)
                    return None
    except Exception as e:
        logger.exception("Download failed for %s: %s", url, e)
        return None
