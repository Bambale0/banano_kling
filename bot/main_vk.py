import asyncio
import json
import logging
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
)

from aiohttp import web
from aiohttp.web import Request, Response
from vkbottle import Bot

from bot.config import config
from bot.database import init_db
from bot.handlers import (
    admin_router,
    batch_generation_router,
    common_router,
    image_analyzer_router,
    payments_router,
)
from bot.handlers.common import common
from bot.handlers.payments import handle_tbank_webhook, handle_yookassa_webhook
from bot.services.kie_webhook import handle_kie_webhook
from bot.services.preset_manager import preset_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

SUPPORTED_EVENT_TYPES = {
    "confirmation",
    "message_new",
    "message_event",
    "group_join",
    "group_leave",
}

bot = Bot(token=config.VK_GROUP_TOKEN)

# Ensure messages with HTML tags are sent with parse_mode='HTML' by default
try:
    _orig_messages_send = bot.api.messages.send

    import re

    async def _messages_send_wrapper(*args, **kwargs):
        try:
            msg = kwargs.get("message")
            # For VK messages: strip HTML tags to avoid raw tags appearing to users
            if isinstance(msg, str) and ("<" in msg and ">" in msg):
                clean = re.sub(r"<[^>]+>", "", msg)
                kwargs["message"] = clean
                # remove parse_mode if present (VK does not interpret HTML)
                if "parse_mode" in kwargs:
                    kwargs.pop("parse_mode")
        except Exception:
            pass
        return await _orig_messages_send(*args, **kwargs)

    bot.api.messages.send = _messages_send_wrapper
except Exception:
    # If structure differs, skip monkeypatch
    pass

# Additionally wrap lower-level API `request` to catch calls that bypass
# `bot.api.messages.send` and ensure HTML tags / parse_mode are removed.
try:
    _orig_api_request = bot.api.request

    async def _api_request_wrapper(method, *args, **kwargs):
        try:
            # Normalize method name
            m = method
            if isinstance(method, str) and method == "messages.send":
                import re

                # message may be in kwargs or inside the first positional dict
                msg = None
                if "message" in kwargs:
                    msg = kwargs.get("message")
                elif args and isinstance(args[0], dict) and "message" in args[0]:
                    msg = args[0].get("message")

                if isinstance(msg, str) and ("<" in msg and ">" in msg):
                    clean = re.sub(r"<[^>]+>", "", msg)
                    if "message" in kwargs:
                        kwargs["message"] = clean
                    elif args and isinstance(args[0], dict) and "message" in args[0]:
                        d = dict(args[0])
                        d["message"] = clean
                        args = (d,) + args[1:]
                    # remove parse_mode if present
                    kwargs.pop("parse_mode", None)
                    if args and isinstance(args[0], dict):
                        d = dict(args[0])
                        d.pop("parse_mode", None)
                        args = (d,) + args[1:]
        except Exception:
            pass
        return await _orig_api_request(method, *args, **kwargs)

    bot.api.request = _api_request_wrapper
except Exception:
    pass

labeler = bot.labeler


def _attach_router(bot_obj, router_obj):
    """Attach blueprint to bot."""
    if router_obj is None:
        logger.info("Router is None, skipping")
        return
    router_name = getattr(router_obj, "name", str(type(router_obj).__name__))
    logger.info(f"Attaching blueprint {router_name} to bot")
    try:
        router_obj.load(bot_obj)
        logger.info(f"blueprint.load(bot) succeeded for {router_name}")
    except Exception as e:
        logger.error(f"Failed to load blueprint {router_name}: {e}")


async def _remove_old_files(
    base_dir: str = "static/uploads", max_age_seconds: int = 6 * 3600
):
    try:
        now = time.time()
        if not os.path.exists(base_dir):
            return
        for root, dirs, files in os.walk(base_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                    if now - mtime > max_age_seconds:
                        os.remove(path)
                        logger.info(f"Removed old file: {path}")
                except Exception:
                    logger.exception(f"Failed to remove file: {path}")
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    logger.info(f"Removed empty dir: {root}")
            except Exception:
                pass
    except Exception:
        logger.exception("Error during static cleanup")


async def _static_cleanup_loop():
    while True:
        try:
            await _remove_old_files("static/uploads", max_age_seconds=6 * 3600)
        except Exception:
            logger.exception("Cleanup iteration failed")
        await asyncio.sleep(6 * 3600)


# async def on_startup():
async def on_startup():
    logger.info("Bot starting...")
    await init_db()
    logger.info("Database initialized successfully")
    if config.WEBHOOK_HOST:
        logger.info(f"Webhook host: {config.webhook_url}")
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")
    asyncio.create_task(_static_cleanup_loop())
    logger.info("Scheduled static cleanup task")


bot.on_startup = on_startup

# async def on_shutdown():
#     logger.info("Bot shutting down...")
#     await bot.close()


def normalize_vk_photo_sizes(event: dict):
    """Normalize VK photo sizes: replace 'base' type with 'max' to fix vkbottle enum validation."""

    def recurse(obj):
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key == "sizes" and isinstance(value, list):
                    obj[key] = [
                        {
                            **size,
                            "type": (
                                "max"
                                if size.get("type") == "base"
                                else size.get("type")
                            ),
                        }
                        for size in value
                        if isinstance(size, dict) and size.get("type")
                    ]
                elif (
                    key == "orig_photo"
                    and isinstance(value, dict)
                    and value.get("type") == "base"
                ):
                    value["type"] = "max"
                recurse(value)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)

    recurse(event["object"])


def verify_vk_signature(payload: str, sig: str, secret_key: str) -> bool:
    import hashlib
    import hmac

    h = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256)
    return hmac.compare_digest(h.hexdigest(), sig)


async def vk_webhook_handler(request: Request) -> Response:
    try:
        # VK sometimes expects a GET response during initial setup but the
        # Callback API primarily uses POST. Keep GET here as a convenience
        # (but Callback API sends a POST with type == 'confirmation').
        if request.method == "GET":
            return web.Response(text=config.VK_CONFIRMATION_TOKEN)

        if request.method == "POST":
            # Read raw body for reliable signature verification
            raw_body = await request.text()
            content_type = request.content_type or ""
            body = None

            # Try to parse JSON body first (recommended for Callback API)
            if content_type.startswith("application/json"):
                try:
                    body = json.loads(raw_body)
                except Exception:
                    logger.exception("Failed to parse JSON body from VK callback")
                    return web.Response(status=400)

                # If this is the confirmation event, return the token
                if isinstance(body, dict) and body.get("type") == "confirmation":
                    return web.Response(text=config.VK_CONFIRMATION_TOKEN)

                # 'object' should be present for real events
                if not body.get("object"):
                    logger.warning("Missing 'object' in VK callback JSON body")
                    return web.Response(status=400)

                # Verify secret/sig if configured
                sig = (
                    body.get("secret")
                    or body.get("sig")
                    or request.headers.get("X-Signature")
                )
                if config.VK_SECRET_KEY:
                    if body.get("secret") is not None:
                        if body.get("secret") != config.VK_SECRET_KEY:
                            logger.warning("Invalid VK secret in JSON body")
                            return web.Response(status=403)
                    elif sig:
                        # HMAC verification: VK signs the whole JSON body
                        if not verify_vk_signature(raw_body, sig, config.VK_SECRET_KEY):
                            logger.warning("Invalid VK signature (json)")
                            return web.Response(status=403)

                # Prepare event payload for vkbottle - pass the full parsed body
                event = body
                normalize_vk_photo_sizes(event)

            else:
                # Fallback: form-encoded POSTs (older setups / some integrations)
                form = await request.post()
                event_data = form.get("object")
                sig = form.get("sig") or request.headers.get("X-Signature")
                if not event_data:
                    logger.warning("Missing 'object' in VK callback form body")
                    return web.Response(status=400)

                # Parse object which is usually a JSON string
                try:
                    parsed = json.loads(event_data)
                except Exception:
                    logger.exception("Failed to parse 'object' from form body")
                    return web.Response(status=400)

                # If confirmation type inside parsed object
                if parsed.get("type") == "confirmation":
                    return web.Response(text=config.VK_CONFIRMATION_TOKEN)

                if config.VK_SECRET_KEY and sig:
                    # For form POSTs the signature is usually computed over the object string
                    if not verify_vk_signature(event_data, sig, config.VK_SECRET_KEY):
                        logger.warning("Invalid VK signature (form)")
                        return web.Response(status=403)

                # vkbottle expects the full structure; try to reconstruct minimal body
                event = {
                    "type": parsed.get("type"),
                    "object": parsed.get("object", parsed),
                }

                normalize_vk_photo_sizes(event)

            event_type = event.get("type")
            if event_type not in SUPPORTED_EVENT_TYPES:
                logger.debug("Ignoring unsupported VK event type: %s", event_type)
                return web.Response(text="ok")

            # Dispatch event through vkbottle's update pipeline with error handling for unknown events
            dispatched = False
            dispatch_errors = []
            candidates = ["labeler.process_event", "bot.process_event", "bot.dispatch"]

            async def safe_process(target):
                try:
                    res = target(event)
                    if asyncio.iscoroutine(res):
                        await res
                    return True
                except ValueError as e:
                    if "GroupEventType" in str(e):
                        logger.debug(
                            f"Ignored unknown VK event type: {event.get('type')}"
                        )
                        return True
                    raise
                except Exception as e:
                    dispatch_errors.append(str(e))
                    raise

            if hasattr(labeler, "process_event"):
                try:
                    res = labeler.process_event(event)
                    if asyncio.iscoroutine(res):
                        await res
                    dispatched = True
                except Exception as e:
                    dispatch_errors.append(f"labeler.process_event: {e}")

            if not dispatched and hasattr(bot, "process_event"):
                try:
                    res = bot.process_event(event)
                    if asyncio.iscoroutine(res):
                        await res
                    dispatched = True
                except Exception as e:
                    dispatch_errors.append(f"bot.process_event: {e}")

            if not dispatched and hasattr(bot, "dispatch"):
                try:
                    res = bot.dispatch(event)
                    if asyncio.iscoroutine(res):
                        await res
                    dispatched = True
                except Exception as e:
                    dispatch_errors.append(f"bot.dispatch: {e}")

            if not dispatched:
                logger.error(
                    "Failed to dispatch VK event; tried candidates: %s; errors: %s",
                    candidates,
                    dispatch_errors,
                )
                return web.Response(status=500)

            return web.Response(text="ok")
    except Exception as e:
        logger.exception(f"VK webhook error: {e}")
        return web.Response(status=500)


def setup_web_server(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot_api"] = bot.api
    app["bot"] = bot
    app.router.add_static("/uploads/", path="static/uploads", show_index=False)
    app.router.add_post(config.WEBHOOK_PATH, vk_webhook_handler)
    app.router.add_post("/tbank/webhook", handle_tbank_webhook)
    app.router.add_post("/yookassa/webhook", handle_yookassa_webhook)
    app.router.add_post("/telegram/webhook", lambda request: web.Response(text="ok"))
    # Add webhook handlers for services if defined
    try:
        from bot.services.kling_service import handle_kling_webhook

        app.router.add_post("/webhook/kling", handle_kling_webhook)
    except ImportError:
        pass

    try:
        from bot.services.kling_service import handle_kling_webhook

        app.router.add_post("/webhook/replicate", handle_kling_webhook)
    except ImportError:
        pass

    try:
        from bot.services.seedream_service import handle_seedream_webhook

        app.router.add_post("/webhook/seedream", handle_seedream_webhook)
    except ImportError:
        pass

    try:
        from bot.services.novita_service import handle_novita_webhook

        app.router.add_post("/webhook/novita", handle_novita_webhook)
    except ImportError:
        pass

    try:
        from bot.services.wanx_service import handle_wanx_webhook

        app.router.add_post("/webhook/wanx", handle_wanx_webhook)
    except ImportError:
        pass

    try:
        from bot.services import handle_kie_webhook

        app.router.add_post("/webhook/kie", handle_kie_webhook)
    except ImportError:
        logger.warning("Kie webhook handler not available")

    # Replicate webhook
    try:
        from bot.services.replicate_service import handle_replicate_webhook

        app.router.add_post("/webhook/replicate", handle_replicate_webhook)
    except ImportError:
        pass

    app.router.add_post("/kie_webhook", handle_kie_webhook)
    app.router.add_post("/webhook/kie_webhook", handle_kie_webhook)

    async def health_check(_: Request) -> Response:
        return web.Response(text="OK")

    app.router.add_get("/health", health_check)
    return app


async def main():
    os.makedirs("logs", exist_ok=True)
    if not config.VK_GROUP_TOKEN:
        logger.error("VK_GROUP_TOKEN is not set!")
        sys.exit(1)
    await init_db()
    preset_manager.load_all()
    logger.info(f"Loaded {len(preset_manager._presets)} presets")
    # Attach vkbottle routers in a version-robust way so VK events are handled.
    try:
        _attach_router(bot, common_router)
        _attach_router(bot, payments_router)
        _attach_router(bot, admin_router)
        _attach_router(bot, batch_generation_router)
        _attach_router(bot, image_analyzer_router)

        logger.info("All routers attached successfully.")

        # Fix for FSM in blueprints
        common_router.state_dispenser = bot.state_dispenser
        payments_router.state_dispenser = bot.state_dispenser
        admin_router.state_dispenser = bot.state_dispenser
        batch_generation_router.state_dispenser = bot.state_dispenser
        image_analyzer_router.state_dispenser = bot.state_dispenser

    except Exception:
        logger.exception("Failed to attach one or more routers to labeler")

    asyncio.create_task(_static_cleanup_loop())
    logger.info("Scheduled static cleanup task")
    if config.WEBHOOK_HOST:
        logger.info("Starting in webhook mode...")
        app = setup_web_server(bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", config.WEBHOOK_PORT)
        await site.start()
        logger.info(f"Server started on port {config.WEBHOOK_PORT}")
        await asyncio.Event().wait()
    else:
        logger.info("Starting in polling mode...")
        await bot.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
