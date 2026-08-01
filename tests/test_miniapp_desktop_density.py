from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "frontend" / "miniapp-v0" / "components"


def _read(relative_path: str) -> str:
    return (COMPONENTS / relative_path).read_text(encoding="utf-8")


def test_desktop_shell_has_bounded_content_width() -> None:
    shell = _read("mini-app-shell.tsx")
    header = _read("hero-header.tsx")

    assert "max-w-[1180px]" in shell
    assert "max-w-[1180px]" in header
    assert "zoom:" not in shell
    assert "scale(" not in shell


def test_desktop_navigation_is_compact_and_centered() -> None:
    navigation = _read("tab-nav.tsx")

    assert "max-w-[900px]" in navigation
    assert "sm:rounded-2xl" in navigation
    assert "lg:py-1.5" in navigation


def test_desktop_studio_uses_denser_grids() -> None:
    quick_actions = _read("quick-action-grid.tsx")
    history = _read("task-history-list.tsx")

    assert "lg:max-w-[920px]" in quick_actions
    assert "md:grid-cols-3" in history
    assert "xl:grid-cols-4" in history
