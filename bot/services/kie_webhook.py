import json
import logging

import aiohttp
import aiohttp.web as web

from bot.database import complete_video_task, get_or_create_user
from bot.handlers.common import safe_clear_state
from bot.keyboards import get_main_menu_keyboard
from bot.utils.file_utils import save_uploaded_file

logger = logging.getLogger(__name__)


async def handle_kie_webhook(request):
    """Handle Kie.ai webhook (Kie format)."""
    try:
        body = await request.json()
        logger.info(f"Kie webhook full payload: {body}")

        if body.get("code") != 200:
            logger.warning(f"Kie webhook non-200 code: {body.get('code')}")
            return web.Response(text="ok")

        data = body["data"]
        task_id = data["taskId"]
        status = data["state"]

        logger.info(f"Kie task {task_id} status: {status}")

        if status != "success":
            logger.warning(f"Kie task {task_id} not success: {status}")
            return web.Response(text="ok")

        # Parse user_id from param
        param_dict = json.loads(data["param"])
        input_str = param_dict["input"]
        input_dict = json.loads(input_str)
        user_id = input_dict.get("user_id")

        if not user_id:
            logger.warning("No user_id in Kie webhook")
            return web.Response(text="ok")

        # Parse output_url from resultJson
        result_dict = json.loads(data["resultJson"])
        output_urls = result_dict.get("resultUrls", [])
        if not output_urls:
            logger.warning(f"No resultUrls for task {task_id}")
            return web.Response(text="ok")
        output_url = output_urls[0]
        logger.info(f"Kie output URL: {output_url}")

        user = await get_or_create_user(int(user_id))
        peer = getattr(user, "vk_user_id", None)
        if not peer:
            logger.warning(f"No VK peer for user {user_id}")
            return web.Response(text="ok")

        bot = request.app["bot"]
        logger.info(f"Processing Kie success for peer {peer}")

        saved_url = output_url

        # Download image
        img_bytes = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(output_url, timeout=60) as resp:
                    resp.raise_for_status()
                    img_bytes = await resp.read()
            logger.info(f"Downloaded Kie image: {len(img_bytes)} bytes")
        except Exception as e:
            logger.error(f"Failed to download {output_url}: {e}")

        # Save to static
        if img_bytes:
            saved_path = save_uploaded_file(img_bytes, "png")
            if saved_path:
                saved_url = saved_path
                logger.info(f"Saved to {saved_path}")

        # Complete task
        await complete_video_task(task_id, saved_url)

        # Clear FSM (VK-specific)
        try:
            await safe_clear_state(peer)
            logger.info(f"FSM cleared for {peer}")
        except Exception as e:
            logger.warning(f"Failed to clear FSM for {peer}: {e}")

        # Send to VK: detect image or video
        try:
            from vkbottle.tools.dev.uploader.photo import PhotoMessageUploader
            from vkbottle.tools.dev.uploader.video import VideoMessageUploader

            from bot.handlers.common import safe_send_vk_photo

            is_video = (
                "mp4" in output_url.lower() or "video" in data.get("model", "").lower()
            )
            caption = (
                f"✅ <b>Видео готово!</b>\n🍌 Баланс: <code>{user.credits or 0}</code>"
            )
            if img_bytes:  # already downloaded
                if is_video:
                    uploader = VideoMessageUploader(bot.api)
                    attachment = await uploader.upload(img_bytes, peer_id=peer)
                else:
                    success = await safe_send_vk_photo(
                        message=type(
                            "obj", (), {"ctx_api": bot.api, "peer_id": peer}
                        )(),
                        image_bytes=img_bytes,
                        caption=caption,
                        keyboard=get_main_menu_keyboard(user.credits or 0),
                    )
                    if success:
                        logger.info(
                            f"✅ Sent Kie { 'video' if is_video else 'image' } to {peer}"
                        )
                        return web.Response(text="ok")
                    attachment = None

                if attachment:
                    await bot.api.messages.send(
                        peer_id=peer,
                        message=caption,
                        attachment=attachment,
                        keyboard=get_main_menu_keyboard(user.credits or 0),
                        random_id=0,
                    )
                    logger.info(f"✅ Sent Kie video to {peer}")
                else:
                    await bot.api.messages.send(
                        peer_id=peer,
                        message=f"{caption}\n\n{saved_url}",
                        keyboard=get_main_menu_keyboard(user.credits or 0),
                        random_id=0,
                        parse_mode="HTML",
                    )
            else:
                await bot.api.messages.send(
                    peer_id=peer,
                    message=f"{caption}\n\n{saved_url}",
                    keyboard=get_main_menu_keyboard(user.credits or 0),
                    random_id=0,
                    parse_mode="HTML",
                )
            logger.info(f"✅ Sent Kie result to {peer}: {saved_url}")
        except Exception as e:
            logger.exception(f"❌ Failed to send Kie result to {peer}: {e}")

        return web.Response(text="ok")
    except Exception as e:
        logger.exception("Kie webhook error")
        return web.Response(status=500)
