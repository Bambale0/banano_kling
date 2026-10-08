"""Offline routing regressions: execute real handler bodies without application imports."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup

ROOT = Path(__file__).resolve().parents[1]


def load_handlers():
    source = ast.parse((ROOT / "bot/handlers/admin_seedance_test_lab.py").read_text())
    names = {
        "SeedanceAdminTestStates", "_show_dashboard", "open_seedance_lab",
        "choose_mode", "finish_prompt", "finish_refs", "finish_frames",
        "receive_dashboard_media",
    }
    nodes = [node for node in source.body if getattr(node, "name", "") in names]
    namespace = {
        "State": State, "StatesGroup": StatesGroup, "F": F,
        "router": Router(), "TelegramAPIError": RuntimeError,
        "_require_admin": AsyncMock(return_value=True),
        "_is_admin": lambda user_id: user_id == 1,
        "_refresh_enabled_models": AsyncMock(),
        "_dashboard_text": lambda data: "Seedance",
        "_dashboard_keyboard": lambda data: None,
        "_MODE_LABELS": {"text": "Text", "reference": "Refs", "frames": "Frames", "edit": "Edit"},
        "receive_reference": AsyncMock(), "receive_frame": AsyncMock(),
    }

    async def data(state):
        return dict(state.data)

    namespace["_normalize_state"] = data
    namespace["_data"] = data
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    tree = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(tree, "<seedance-handler-bodies>", "exec"), namespace)  # noqa: S102
    return namespace


class FakeState:
    def __init__(self):
        self.value = None
        self.data = {"seedance_admin_model": "seedance-2.5", "seedance_admin_mode": "text"}

    async def set_state(self, value):
        self.value = value.state if isinstance(value, State) else value

    async def get_state(self):
        return self.value

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def clear(self):
        self.value = None
        self.data.clear()


def idle_photo_filter():
    tree = ast.parse((ROOT / "bot/handlers/generation.py").read_text())
    handler = next(node for node in tree.body if getattr(node, "name", "") == "start_image_creation_from_idle_reference")
    expression = handler.decorator_list[0].args[0]
    return eval(compile(ast.Expression(expression), "<real-idle-filter>", "eval"), {"StateFilter": StateFilter})


class SeedanceRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.lab = load_handlers()
        self.state = FakeState()
        self.message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock(), from_user=SimpleNamespace(id=1))
        self.callback = SimpleNamespace(message=self.message, answer=AsyncMock(), from_user=SimpleNamespace(id=1), data="")
        self.idle_filter = idle_photo_filter()

    async def assert_not_idle(self):
        self.assertFalse(await self.idle_filter(self.message, raw_state=await self.state.get_state()),
                         "Seedance dashboard photo is accepted by NanoBanana idle handler")

    async def test_open_and_select_reference_mode_blocks_idle_quick_launch(self):
        await self.lab["open_seedance_lab"](self.callback, self.state)
        self.callback.data = "admin_seedance_mode:reference"
        await self.lab["choose_mode"](self.callback, self.state)
        await self.assert_not_idle()
        self.assertEqual(self.state.data["seedance_admin_mode"], "reference")

    async def test_dashboard_returns_never_release_seedance_session_to_idle(self):
        for name in ("finish_prompt", "finish_refs", "finish_frames"):
            with self.subTest(handler=name):
                await self.lab[name](self.callback, self.state)
                await self.assert_not_idle()

    async def test_switch_mode_from_prompt_enters_dashboard(self):
        await self.state.set_state(self.lab["SeedanceAdminTestStates"].prompt)
        self.callback.data = "admin_seedance_mode:frames"
        await self.lab["choose_mode"](self.callback, self.state)
        self.assertEqual(await self.state.get_state(), "SeedanceAdminTestStates:dashboard")

    async def test_dashboard_routes_selected_media_without_provider_calls(self):
        self.assertIn("receive_dashboard_media", self.lab)
        for mode, target in (("reference", "receive_reference"), ("edit", "receive_reference"), ("frames", "receive_frame")):
            with self.subTest(mode=mode):
                self.state.data["seedance_admin_mode"] = mode
                await self.lab["receive_dashboard_media"](self.message, self.state)
                self.lab[target].assert_awaited_with(self.message, self.state)
        self.state.data["seedance_admin_mode"] = "text"
        await self.lab["receive_dashboard_media"](self.message, self.state)
        self.message.answer.assert_awaited()

    async def test_first_matching_router_preserves_seedance_photo_and_idle_shortcut(self):
        source = ast.parse((ROOT / "bot/handlers/generation.py").read_text())
        node = next(node for node in source.body if getattr(node, "name", "") == "start_image_creation_from_idle_reference")
        filters = [
            eval(compile(ast.Expression(arg), "<real-quick-filter>", "eval"), {
                "StateFilter": StateFilter, "F": F,
                "IMAGE_REFERENCE_DOCUMENT_MIME_TYPES": {"image/jpeg", "image/png"},
            })
            for arg in node.decorator_list[0].args
        ]
        quick = Router()
        quick_hit = AsyncMock()

        @quick.message(*filters)
        async def quick_upload(message):
            await quick_hit(message)

        root = Router()
        root.include_router(quick)
        root.include_router(self.lab["router"])
        self.message.photo = [SimpleNamespace(file_id="synthetic-photo")]
        self.message.document = None
        await self.lab["open_seedance_lab"](self.callback, self.state)
        self.callback.data = "admin_seedance_mode:reference"
        await self.lab["choose_mode"](self.callback, self.state)
        await root.propagate_event(
            update_type="message", event=self.message, state=self.state,
            raw_state=await self.state.get_state(),
        )
        quick_hit.assert_not_awaited()
        self.lab["receive_reference"].assert_awaited_once_with(self.message, self.state)
        await self.state.clear()
        await root.propagate_event(
            update_type="message", event=self.message, state=self.state, raw_state=None,
        )
        quick_hit.assert_awaited_once_with(self.message)

    async def test_non_admin_dashboard_does_not_route_media(self):
        self.assertIn("receive_dashboard_media", self.lab)
        self.message.from_user.id = 2
        await self.lab["receive_dashboard_media"](self.message, self.state)
        self.lab["receive_reference"].assert_not_awaited()
        self.lab["receive_frame"].assert_not_awaited()

    async def test_normal_idle_and_active_seedance_filters_unchanged(self):
        self.assertTrue(await self.idle_filter(self.message, raw_state=None))
        self.assertTrue(await self.idle_filter(self.message, raw_state="AIAssistantStates:waiting_for_message"))
        for state in ("references", "frames", "prompt"):
            self.assertFalse(await self.idle_filter(self.message, raw_state="SeedanceAdminTestStates:" + state))

    async def test_admin_access_allowlist_includes_dashboard(self):
        source = (ROOT / "bot/main.py").read_text()
        self.assertIn('"SeedanceAdminTestStates:dashboard"', source)


if __name__ == "__main__":
    unittest.main()
