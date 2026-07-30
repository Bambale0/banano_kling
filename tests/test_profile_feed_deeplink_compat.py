import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "bot"
    / "handlers"
    / "profile_feed_deeplink_compat.py"
)
SPEC = importlib.util.spec_from_file_location(
    "profile_feed_deeplink_compat_under_test",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
compat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compat)


def _install_with_card(card):
    calls = []

    async def original_renderer(message, user, gen_id, *, state=None, open_repeat=False):
        calls.append(("original", gen_id, state, open_repeat))
        return "original-result"

    async def get_profile_card(gen_id, *, viewer_user_id=None, include_unavailable=False):
        calls.append(
            (
                "lookup",
                gen_id,
                viewer_user_id,
                include_unavailable,
            )
        )
        return card

    async def render_carousel(message, cards, **kwargs):
        calls.append(("carousel", cards, kwargs))

    common_module = SimpleNamespace(
        _render_feed_deeplink=original_renderer,
        get_profile_generation_card=get_profile_card,
        _render_feed_carousel=render_carousel,
    )
    compat._INSTALLED = False
    compat.install_profile_feed_deeplink_compat(common_module)
    return common_module, calls


def test_profile_only_feed_link_renders_exact_card_without_discovery_lookup():
    card = {
        "id": 158662,
        "publication_scope": "profile",
        "is_profile_visible": True,
        "is_public_feed": False,
        "author_referral_code": "sel4dqap",
    }
    common_module, calls = _install_with_card(card)

    result = asyncio.run(
        common_module._render_feed_deeplink(
            object(),
            SimpleNamespace(id=77),
            "158662",
        )
    )

    assert result is True
    assert calls[0] == ("lookup", "158662", 77, True)
    assert calls[1][0] == "carousel"
    assert calls[1][1] == [card]
    assert calls[1][2]["source_code"] == "m"
    assert calls[1][2]["profile_code"] == "SEL4DQAP"
    assert not any(call[0] == "original" for call in calls)


def test_public_feed_link_keeps_existing_renderer():
    card = {
        "id": 42,
        "publication_scope": "feed",
        "is_profile_visible": True,
        "is_public_feed": True,
    }
    common_module, calls = _install_with_card(card)

    result = asyncio.run(
        common_module._render_feed_deeplink(
            object(),
            SimpleNamespace(id=77),
            "42",
            state="state",
            open_repeat=True,
        )
    )

    assert result == "original-result"
    assert calls[0] == ("lookup", "42", 77, True)
    assert calls[1] == ("original", "42", "state", True)
