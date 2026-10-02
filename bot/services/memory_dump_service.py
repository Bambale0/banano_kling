import gc
import json
import os
import platform
import resource
import tracemalloc
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def ensure_memory_tracing() -> None:
    """Enable expensive allocation tracing only for explicit diagnostics."""
    enabled = os.getenv("MEMORY_TRACING_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled or tracemalloc.is_tracing():
        return
    try:
        frames = int(os.getenv("MEMORY_TRACING_FRAMES", "1"))
    except ValueError:
        frames = 1
    tracemalloc.start(max(1, min(frames, 25)))


def _read_proc_status() -> dict[str, str]:
    status_path = Path("/proc/self/status")
    if not status_path.exists():
        return {}

    status: dict[str, str] = {}
    try:
        for line in status_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                status[key.strip()] = value.strip()
    except OSError:
        return {}
    return status


def _read_smaps_rollup() -> dict[str, str]:
    smaps_path = Path("/proc/self/smaps_rollup")
    if not smaps_path.exists():
        return {}

    rollup: dict[str, str] = {}
    try:
        for line in smaps_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                rollup[key.strip()] = value.strip()
    except OSError:
        return {}
    return rollup


def _format_tracemalloc_stat(stat: tracemalloc.Statistic) -> dict[str, Any]:
    frame = stat.traceback[0]
    return {
        "file": frame.filename,
        "line": frame.lineno,
        "size_bytes": stat.size,
        "count": stat.count,
        "traceback": [
            {
                "file": frame.filename,
                "line": frame.lineno,
            }
            for frame in stat.traceback
        ],
    }


def build_memory_dump() -> tuple[bytes, str, str]:
    ensure_memory_tracing()

    collected = gc.collect()
    tracing_enabled = tracemalloc.is_tracing()
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    top_allocations = (
        tracemalloc.take_snapshot().statistics("traceback")[:50]
        if tracing_enabled
        else []
    )
    object_type_counts = Counter(
        type(obj).__name__ for obj in gc.get_objects()
    ).most_common(100)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    dump = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "process": {
            "pid": os.getpid(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "memory": {
            "proc_status": _read_proc_status(),
            "smaps_rollup": _read_smaps_rollup(),
            "resource_rusage": {
                "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            "tracemalloc": {
                "enabled": tracing_enabled,
                "traceback_limit": tracemalloc.get_traceback_limit()
                if tracing_enabled
                else 0,
                "current_bytes": current_bytes,
                "peak_bytes": peak_bytes,
                "top_allocations": [
                    _format_tracemalloc_stat(stat) for stat in top_allocations
                ],
            },
        },
        "gc": {
            "collected_before_dump": collected,
            "counts": gc.get_count(),
            "thresholds": gc.get_threshold(),
            "object_type_counts": [
                {"type": type_name, "count": count}
                for type_name, count in object_type_counts
            ],
        },
    }

    data = json.dumps(dump, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    filename = f"banano_kling_memory_dump_{timestamp}.json"
    caption = (
        "banano_kling memory dump\n"
        f"UTC: {dump['generated_at']}\n"
        f"PID: {dump['process']['pid']}\n"
        f"RSS: {dump['memory']['proc_status'].get('VmRSS', 'n/a')}\n"
        + (
            f"tracemalloc current: {current_bytes // 1024} KiB, peak: {peak_bytes // 1024} KiB"
            if tracing_enabled
            else "tracemalloc: disabled"
        )
    )
    return data, filename, caption
