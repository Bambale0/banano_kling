#!/usr/bin/env python3
from pathlib import Path

MAIN_PATH = Path("bot/main.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise SystemExit(f"Patch marker not found: {old!r}")
    if count != 1:
        raise SystemExit(f"Patch marker is ambiguous ({count} matches): {old!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from bot.miniapp import setup_miniapp_routes\n",
        "from bot.browser_auth import setup_browser_auth_routes\n"
        "from bot.miniapp import setup_miniapp_routes\n",
    )
    text = replace_once(
        text,
        "    setup_miniapp_routes(app)\n",
        "    setup_browser_auth_routes(app)\n"
        "    setup_miniapp_routes(app)\n",
    )
    MAIN_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
