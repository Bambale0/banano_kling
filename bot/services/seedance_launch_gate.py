"""Operational pause for NEW measured Seedance claims; recovery is unaffected."""
from pathlib import Path

PAUSE_MARKER = Path(__file__).resolve().parents[2] / "data" / "seedance-launches.paused"
PAUSE_MESSAGE = "Новые запуски Seedance временно приостановлены. Уже принятые задачи продолжаются."


def launches_allowed(path: Path = PAUSE_MARKER) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False
