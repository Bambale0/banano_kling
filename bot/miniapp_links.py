from urllib.parse import quote

from bot.config import config


def _clean_bot_username(bot_username: str | None) -> str:
    return str(bot_username or "").strip().lstrip("@")


def _clean_referral_code(referral_code: str | None) -> str:
    return str(referral_code or "").strip().upper()


def _clean_vk_app_id(vk_app_id: int | str | None) -> int:
    try:
        value = int(vk_app_id or 0)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise ValueError("VK Mini App ID is not configured")
    return value


def _clean_vk_community_id(vk_community_id: int | str | None) -> int | None:
    # A missing community is a valid *legacy* app. An explicitly configured
    # but malformed community must fail closed, not create an unrelated link.
    if vk_community_id is None:
        return None
    raw = str(vk_community_id)
    if type(vk_community_id) not in (int, str) or not raw.isascii() or not raw.isdecimal():
        raise ValueError("VK community ID is invalid")
    value = int(raw)
    if not 0 < value < 2**63:
        raise ValueError("VK community ID is invalid")
    return value


def miniapp_startapp_link(
    bot_username: str | None,
    start_param: str | None = None,
    *,
    fallback_url: str | None = None,
) -> str:
    username = _clean_bot_username(bot_username)
    if not username:
        return fallback_url or config.mini_app_url

    param = str(start_param or "").strip()
    if not param:
        return f"https://t.me/{username}?startapp"
    return f"https://t.me/{username}?startapp={quote(param, safe='_-')}"


def platform_miniapp_link(
    bot_username: str | None,
    start_param: str | None = None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
    fallback_url: str | None = None,
) -> str:
    if str(platform or "").strip().lower() != "vk":
        return miniapp_startapp_link(
            bot_username,
            start_param,
            fallback_url=fallback_url,
        )
    base = f"https://vk.com/app{_clean_vk_app_id(vk_app_id)}"
    community_id = _clean_vk_community_id(vk_community_id)
    if community_id is not None:
        base += f"_-{community_id}"
    param = str(start_param or "").strip()
    return f"{base}#{quote(param, safe='_-')}" if param else base


def bot_start_link(
    bot_username: str | None,
    start_param: str | None = None,
    *,
    fallback_url: str | None = None,
) -> str:
    username = _clean_bot_username(bot_username)
    if not username:
        return fallback_url or config.mini_app_url

    param = str(start_param or "").strip()
    if not param:
        return f"https://t.me/{username}"
    return f"https://t.me/{username}?start={quote(param, safe='_-')}"


def referral_start_param(referral_code: str | None) -> str:
    code = _clean_referral_code(referral_code)
    return f"ref_{code}" if code else ""


def referral_link(
    bot_username: str | None,
    referral_code: str | None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    """Партнёрская ссылка на текущее мини-приложение."""
    return platform_miniapp_link(
        bot_username,
        referral_start_param(referral_code),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )


def referral_bot_link(bot_username: str | None, referral_code: str | None) -> str:
    """Партнёрская ссылка на Telegram-бота (?start=ref_CODE)."""
    return bot_start_link(bot_username, referral_start_param(referral_code))


def profile_start_param(referral_code: str | None) -> str:
    code = _clean_referral_code(referral_code)
    return f"profile_{code}_ref_{code}" if code else ""


def profile_link(
    bot_username: str | None,
    referral_code: str | None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    return platform_miniapp_link(
        bot_username,
        profile_start_param(referral_code),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )


def feed_start_param(gen_id: int | str, referral_code: str | None = None) -> str:
    value = str(gen_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"feed_{value}"
    return f"{base}_ref_{code}" if code else base


def feed_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    return platform_miniapp_link(
        bot_username,
        feed_start_param(gen_id, referral_code),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )


def feed_bot_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return bot_start_link(bot_username, feed_start_param(gen_id, referral_code))


def remix_start_param(gen_id: int | str, referral_code: str | None = None) -> str:
    value = str(gen_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"remix_{value}"
    return f"{base}_ref_{code}" if code else base


def remix_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    return platform_miniapp_link(
        bot_username,
        remix_start_param(gen_id, referral_code),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )


def remix_bot_link(
    bot_username: str | None,
    gen_id: int | str,
    referral_code: str | None = None,
) -> str:
    return bot_start_link(bot_username, remix_start_param(gen_id, referral_code))


def prompt_start_param(prompt_id: int | str, referral_code: str | None = None) -> str:
    value = str(prompt_id or "").strip()
    if not value:
        return ""
    code = _clean_referral_code(referral_code)
    base = f"prompt_{value}"
    return f"{base}_ref_{code}" if code else base


def prompt_link(
    bot_username: str | None,
    prompt_id: int | str,
    referral_code: str | None = None,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    return platform_miniapp_link(
        bot_username,
        prompt_start_param(prompt_id, referral_code),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )


def task_start_param(task_id: int | str) -> str:
    value = str(task_id or "").strip()
    return f"task_{value}" if value else ""


def task_link(
    bot_username: str | None,
    task_id: int | str,
    *,
    platform: str = "telegram",
    vk_app_id: int | str | None = None,
    vk_community_id: int | str | None = None,
) -> str:
    return platform_miniapp_link(
        bot_username,
        task_start_param(task_id),
        platform=platform,
        vk_app_id=vk_app_id,
        vk_community_id=vk_community_id,
    )
