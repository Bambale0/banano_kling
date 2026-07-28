from pathlib import Path
import re
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import scripts.apply_profile_publication_scope as publication_patch  # noqa: E402


def flexible_replace_once(path: str, old: str, new: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    exact_count = text.count(old)
    if exact_count == 1:
        Path(path).write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    if exact_count > 1:
        raise AssertionError(
            f"{path}: expected one exact anchor, got {exact_count}: {old[:120]!r}"
        )

    parts = re.split(r"([ \t]+)", old)
    pattern = "".join(r"[ \t]*" if part and part.isspace() and "\n" not in part else re.escape(part) for part in parts)
    next_text, count = re.subn(pattern, lambda _match: new, text, count=1)
    if count != 1:
        raise AssertionError(
            f"{path}: expected one whitespace-tolerant anchor, got {count}: {old[:120]!r}"
        )
    Path(path).write_text(next_text, encoding="utf-8")


def main() -> None:
    publication_patch.replace_once = flexible_replace_once
    publication_patch.patch_miniapp()
    publication_patch.patch_schema()
    publication_patch.patch_frontend_contracts()
    publication_patch.patch_task_detail()
    publication_patch.patch_profile()
    publication_patch.patch_tests()
    publication_patch.patch_docs()

    miniapp_path = Path("bot/miniapp.py")
    miniapp_text = miniapp_path.read_text(encoding="utf-8")
    miniapp_text = miniapp_text.replace(
        "    get_feed_generations,\n    get_profile_generation_card,\n",
        "    get_feed_generations,\n",
        1,
    )
    miniapp_path.write_text(miniapp_text, encoding="utf-8")

    Path("scripts/apply_profile_publication_scope.py").unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
