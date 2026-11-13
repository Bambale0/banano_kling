import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot import database, miniapp


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partner_balance", "repeat_balance", "repeat_total", "pending", "expected"),
    [
        (100.0, 70.0, 90.0, 35.0, (65.0, 90.0)),
        (100.0, 70.0, 90.0, 0.0, (70.0, 90.0)),
        (25.0, 70.0, 90.0, 100.0, (0.0, 90.0)),
        (25.0, 70.0, 90.0, None, (25.0, 90.0)),
    ],
)
async def test_bootstrap_repeat_snapshot_preserves_pending_withdrawal_math(
    monkeypatch, partner_balance, repeat_balance, repeat_total, pending, expected
):
    calls = []

    class Cursor:
        async def fetchone(self):
            return {"pending": pending}

    class Conn:
        row_factory = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, sql, params):
            calls.append((sql, params))
            return Cursor()

    monkeypatch.setattr(database.db_backend, "connect", lambda *_: Conn())
    user = SimpleNamespace(
        id=137,
        partner_balance_rub=partner_balance,
        prompt_repeat_balance_rub=repeat_balance,
        prompt_repeat_total_rub=repeat_total,
    )

    result = await database.get_miniapp_prompt_repeat_snapshot(user)
    assert result == {
        "prompt_repeat_balance_rub": expected[0],
        "prompt_repeat_total_rub": expected[1],
    }
    assert len(calls) == 1
    sql, params = calls[0]
    assert "partner_withdrawals" in sql
    assert "status = 'requested'" in sql
    assert params == (137,)


def test_bootstrap_never_runs_full_partner_analytics():
    # Another regression suite monkeypatches the exported callable at import time.
    # Inspect the actual production handler, not a test-installed wrapper.
    module_source = Path(miniapp.__file__).read_text(encoding="utf-8")
    source = module_source.split("async def miniapp_bootstrap(", 1)[1].split(
        "\n\nasync def miniapp_write_access(", 1
    )[0]
    assert "get_partner_overview(" not in source
    assert "get_miniapp_prompt_repeat_snapshot(" in source


def test_full_partner_overview_does_not_hold_a_connection_while_loading_actor():
    source = inspect.getsource(database.get_partner_overview)
    assert source.index(
        "target_user = await get_or_create_user(telegram_id)"
    ) < source.index("async with db_backend.connect(DATABASE_PATH) as db:")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ids", "expected_deletes"),
    [([], 0), ([11, 14], 1), (list(range(1, 1002)), 2)],
)
async def test_bootstrap_notification_drain_deletes_only_observed_notifications(
    monkeypatch, ids, expected_deletes
):
    statements = []
    commits = []

    class Cursor:
        def __init__(self, kind):
            self.kind = kind

        async def fetchone(self):
            if self.kind == "user":
                return {"id": 137}
            return None

        async def fetchall(self):
            return [{"id": i, "message": f"note {i}"} for i in ids]

    class Conn:
        row_factory = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, sql, params):
            statements.append((sql, params))
            return Cursor("user" if "SELECT id FROM users" in sql else "notes")

        async def commit(self):
            commits.append(1)

    monkeypatch.setattr(database.db_backend, "connect", lambda *_: Conn())
    output = await database.get_and_clear_miniapp_notifications(999)
    assert output == [f"note {i}" for i in ids]
    delete_calls = [(sql, values) for sql, values in statements if "DELETE" in sql]
    assert len(delete_calls) == expected_deletes
    assert len(commits) == (1 if ids else 0)
    if ids:
        seen_ids = []
        for sql, values in delete_calls:
            assert "WHERE id IN (" in sql
            assert len(values) <= 999
            assert values[-1] == 137
            seen_ids.extend(values[:-1])
        assert seen_ids == ids


@pytest.mark.parametrize(
    ("s3_enabled", "expected_count", "expected_resolves"),
    [(True, 24, 0), (False, 0, 24)],
)
def test_saved_reference_list_never_materializes_s3_files_on_bootstrap(
    monkeypatch, s3_enabled, expected_count, expected_resolves
):
    from bot.services import media_input_utils, media_storage

    resolves = []

    def fake_materialize(source):
        resolves.append(source)

    monkeypatch.setattr(media_storage, "is_s3_enabled", lambda: s3_enabled)
    monkeypatch.setattr(
        media_input_utils, "resolve_local_upload_path", fake_materialize
    )
    references = [
        database.SavedReference(
            id=i,
            user_id=137,
            kind="image",
            file_url=f"/uploads/refs/image/137/202611/{i}.png",
            file_hash=str(i),
        )
        for i in range(24)
    ]
    available = database._filter_available_saved_references(references, limit=24)
    assert len(available) == expected_count
    assert len(resolves) == expected_resolves
