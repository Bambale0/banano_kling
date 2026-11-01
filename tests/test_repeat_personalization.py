import pytest

from bot import repeat_personalization as subject

BASE = (
    "Cinematic birthday scene. The hero wears a blue coat and carries a chocolate cake. "
    "Keep the camera move, lighting and reference identity unchanged."
)


def _fields():
    return [
        {"key": "clothes", "label": "Одежда", "original_value": "blue coat"},
        {"key": "object", "label": "Предмет", "original_value": "chocolate cake"},
    ]


def test_preview_flag_is_default_off(monkeypatch):
    monkeypatch.delenv(subject.FEATURE_FLAG, raising=False)
    assert subject.admin_preview_enabled() is False


def test_normalized_public_fields_never_expose_private_bindings():
    fields = subject.normalize_repeat_fields(_fields(), prompt=BASE)
    public = subject.public_repeat_fields(fields)

    assert [field["label"] for field in public] == ["Одежда", "Предмет"]
    assert all("original_value" not in field for field in public)
    assert "blue coat" not in repr(public)
    assert "chocolate cake" not in repr(public)


def test_personalized_repeat_preserves_base_and_applies_only_declared_values():
    fields = subject.normalize_repeat_fields(_fields(), prompt=BASE)

    rendered = subject.render_repeat_base(
        BASE,
        fields,
        {"clothes": "red dress", "object": "strawberry cake"},
    )

    assert "Cinematic birthday scene" in rendered
    assert "Keep the camera move, lighting and reference identity unchanged" in rendered
    assert "red dress" in rendered
    assert "strawberry cake" in rendered
    assert "blue coat" not in rendered
    assert "chocolate cake" not in rendered


def test_curated_choices_are_public_but_bindings_are_not_and_values_are_allowlisted():
    raw = [{
        "key": "clothes", "label": "Одежда", "original_value": "blue coat",
        "choices": ["red dress", "black suit"],
    }]
    fields = subject.normalize_repeat_fields(raw, prompt=BASE)
    assert subject.public_repeat_fields(fields)[0]["choices"] == ["red dress", "black suit"]
    assert "original_value" not in subject.public_repeat_fields(fields)[0]
    assert "red dress" in subject.render_repeat_base(BASE, fields, {"clothes": "red dress"})
    with pytest.raises(ValueError, match="Выберите один"):
        subject.render_repeat_base(BASE, fields, {"clothes": "unlisted hoodie"})


def test_overlapping_bindings_are_rejected_before_publication():
    with pytest.raises(ValueError, match="пересекаться"):
        subject.normalize_repeat_fields([
            {"key": "outfit", "label": "Образ", "original_value": "blue coat"},
            {"key": "item", "label": "Вещь", "original_value": "coat"},
        ], prompt=BASE)


def test_word_boundary_bindings_that_only_share_letters_are_allowed():
    fields = subject.normalize_repeat_fields([
        {"key": "person_a", "label": "Первый", "original_value": "man"},
        {"key": "person_b", "label": "Вторая", "original_value": "woman"},
    ], prompt="A man and a woman stand together")
    assert [field["key"] for field in fields] == ["person_a", "person_b"]


def test_explicit_empty_fields_clear_even_when_prompt_contains_legacy_tokens():
    assert subject.normalize_repeat_fields([], prompt="Scene with {{clothes}}") == []


@pytest.mark.parametrize("values", [None, {}, {"unknown": "value"}])
def test_structured_values_are_complete_and_allowlisted(values):
    fields = subject.normalize_repeat_fields(_fields(), prompt=BASE)
    with pytest.raises(ValueError):
        subject.render_repeat_base(BASE, fields, values)


async def test_repeat_fields_round_trip_by_generation_id(isolated_database):
    fields = subject.normalize_repeat_fields(_fields(), prompt=BASE)
    await subject.save_repeat_fields(42, fields, actor_telegram_id=123456)

    assert await subject.get_repeat_fields(42) == fields
    assert await subject.get_repeat_fields_many([41, 42, 43]) == {42: fields}

    await subject.clear_repeat_fields(42, actor_telegram_id=123456)
    assert await subject.get_repeat_fields(42) == []


async def test_stale_rollback_never_overwrites_a_newer_success(isolated_database):
    previous = subject.normalize_repeat_fields(_fields(), prompt=BASE)
    first = subject.normalize_repeat_fields([{
        "key": "clothes", "label": "Одежда", "original_value": "blue coat",
        "choices": ["red dress"],
    }], prompt=BASE)
    newer = subject.normalize_repeat_fields([{
        "key": "object", "label": "Предмет", "original_value": "chocolate cake",
        "choices": ["strawberry cake"],
    }], prompt=BASE)
    await subject.save_repeat_fields(42, previous, actor_telegram_id=1)
    first_token, first_previous = await subject.save_repeat_fields(
        42, first, actor_telegram_id=2,
    )
    await subject.save_repeat_fields(42, newer, actor_telegram_id=3)

    restored = await subject.restore_repeat_fields_if_current(
        42,
        expected_token=first_token,
        previous_fields=first_previous,
        actor_telegram_id=2,
    )

    assert restored is False
    assert await subject.get_repeat_fields(42) == newer


async def test_stale_rollback_never_overwrites_same_content_newer_success(isolated_database):
    previous = subject.normalize_repeat_fields(_fields(), prompt=BASE)
    repeated = subject.normalize_repeat_fields([{
        "key": "clothes", "label": "Одежда", "original_value": "blue coat",
        "choices": ["red dress"],
    }], prompt=BASE)
    await subject.save_repeat_fields(42, previous, actor_telegram_id=1)
    first_token, first_previous = await subject.save_repeat_fields(
        42, repeated, actor_telegram_id=2,
    )
    await subject.save_repeat_fields(42, repeated, actor_telegram_id=3)

    restored = await subject.restore_repeat_fields_if_current(
        42,
        expected_token=first_token,
        previous_fields=first_previous,
        actor_telegram_id=2,
    )

    assert restored is False
    assert await subject.get_repeat_fields(42) == repeated


async def test_postgres_locks_parent_before_reading_previous_revision(monkeypatch):
    statements = []

    class Cursor:
        async def fetchone(self):
            return None

    class Connection:
        row_factory = None

        async def execute(self, sql, params=()):
            statements.append((" ".join(sql.split()), params))
            return Cursor()

        async def commit(self):
            statements.append(("COMMIT", ()))

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(subject.db_backend, "is_postgres", lambda: True)
    monkeypatch.setattr(subject.db_backend, "connect", lambda: Context())

    await subject.save_repeat_fields(42, [], actor_telegram_id=123456)

    assert statements[0][0] == "BEGIN"
    assert statements[1] == (
        "SELECT id FROM generation_tasks WHERE id = ? FOR UPDATE", (42,),
    )
    assert statements[2] == (
        "SELECT fields_json FROM generation_repeat_personalization WHERE generation_id = ?",
        (42,),
    )
