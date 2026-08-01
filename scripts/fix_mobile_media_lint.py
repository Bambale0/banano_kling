from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected source block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "bot/miniapp.py",
        """from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    missing_local_upload_sources,
    resolve_local_upload_path,
)
""",
        """from bot.services.media_input_utils import (
    missing_local_upload_sources,
    resolve_local_upload_path,
)
""",
    )
    replace_once(
        "bot/miniapp.py",
        """def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    file_url = reference.file_url
    if reference.kind == "image":
        file_url = image_source_to_provider_safe_png_url(file_url)
""",
        """def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    file_url = reference.file_url
    if reference.kind == "image":
        from bot.services.media_input_utils import image_source_to_provider_safe_png_url

        file_url = image_source_to_provider_safe_png_url(file_url)
""",
    )
    replace_once(
        "bot/miniapp.py",
        """        import io  # noqa: PLC0415

        from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

        try:
            from pillow_heif import register_heif_opener  # noqa: PLC0415
""",
        """        import io

        from PIL import Image, UnidentifiedImageError

        try:
            from pillow_heif import register_heif_opener
""",
    )
    replace_once(
        "bot/services/photo_prompt_service.py",
        "def _build_claude_image_source(image_url: str) -> Dict[str, str]:\n",
        "def _build_claude_image_source(image_url: str) -> dict[str, str]:\n",
    )
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
