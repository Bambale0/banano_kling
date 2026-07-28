from pathlib import Path

from scripts.apply_profile_publication_scope import (
    patch_docs,
    patch_frontend_contracts,
    patch_miniapp,
    patch_profile,
    patch_schema,
    patch_task_detail,
    patch_tests,
)


def main() -> None:
    patch_miniapp()
    patch_schema()
    patch_frontend_contracts()
    patch_task_detail()
    patch_profile()
    patch_tests()
    patch_docs()

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
