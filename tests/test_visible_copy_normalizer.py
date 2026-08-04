from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_copy_normalizer_uses_shared_welcome_bonus(tmp_path: Path) -> None:
    files = (
        "scripts/apply_visible_copy_fixes.py",
        "bot/keyboards.py",
        "bot/database.py",
        "bot/handlers/common.py",
        "bot/handlers/image_analyzer.py",
    )

    for relative_path in files:
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    subprocess.run(
        [sys.executable, "scripts/apply_visible_copy_fixes.py"],
        cwd=tmp_path,
        check=True,
    )

    common = (tmp_path / "bot/handlers/common.py").read_text(encoding="utf-8")
    assert "    PARTNER_NEW_USER_BONUS,\n" in common
    assert (
        'f"🎁 <b>Новым пользователям — {PARTNER_NEW_USER_BONUS} '
        'бананов в подарок!</b>\\n"'
    ) in common
    assert (
        'f"  🍌 {PARTNER_NEW_USER_BONUS} бананов для тестирования бота\\n"'
    ) in common
    assert "Новым пользователям — 15 бананов" not in common
    assert "15 бананов для тестирования бота" not in common
    assert common.count("{PARTNER_NEW_USER_BONUS}") >= 2
