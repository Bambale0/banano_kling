"""Production diagnostics must not trace every allocation unless opted in."""

import json
import tracemalloc

import pytest

from bot.services.memory_dump_service import build_memory_dump, ensure_memory_tracing


@pytest.fixture(autouse=True)
def isolated_tracing(monkeypatch):
    previous_frames = (
        tracemalloc.get_traceback_limit() if tracemalloc.is_tracing() else None
    )
    tracemalloc.stop()
    monkeypatch.delenv("MEMORY_TRACING_ENABLED", raising=False)
    monkeypatch.delenv("MEMORY_TRACING_FRAMES", raising=False)
    yield
    tracemalloc.stop()
    if previous_frames is not None:
        tracemalloc.start(previous_frames)


def test_startup_does_not_enable_allocation_tracing_by_default():
    ensure_memory_tracing()
    assert not tracemalloc.is_tracing()


def test_periodic_dump_preserves_process_metrics_without_enabling_tracing():
    data, filename, caption = build_memory_dump()
    payload = json.loads(data)
    assert not tracemalloc.is_tracing()
    assert payload["memory"]["tracemalloc"]["enabled"] is False
    assert payload["memory"]["tracemalloc"]["top_allocations"] == []
    assert payload["memory"]["resource_rusage"]["maxrss_kb"] > 0
    assert payload["gc"]["object_type_counts"]
    assert filename.endswith(".json")
    assert "disabled" in caption


@pytest.mark.parametrize(
    "frames, expected", [("2", 2), ("invalid", 1), ("999", 25), ("0", 1)]
)
def test_diagnostic_tracing_is_explicit_and_bounded(monkeypatch, frames, expected):
    monkeypatch.setenv("MEMORY_TRACING_ENABLED", "true")
    monkeypatch.setenv("MEMORY_TRACING_FRAMES", frames)
    ensure_memory_tracing()
    assert tracemalloc.is_tracing()
    assert tracemalloc.get_traceback_limit() == expected
    data, _, _ = build_memory_dump()
    assert json.loads(data)["memory"]["tracemalloc"]["enabled"] is True


def test_existing_runtime_tracing_preserves_its_depth():
    tracemalloc.start(2)
    ensure_memory_tracing()
    data, _, _ = build_memory_dump()
    assert tracemalloc.is_tracing()
    assert tracemalloc.get_traceback_limit() == 2
    allocation_report = json.loads(data)["memory"]["tracemalloc"]
    assert allocation_report["enabled"] is True
    assert allocation_report["traceback_limit"] == 2
