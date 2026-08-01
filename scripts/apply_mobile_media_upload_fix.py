from pathlib import Path


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if marker in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected source block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "frontend/miniapp-v0/components/workspace-sheet.tsx",
        """      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      toast.success('Фото загружено')
""",
        """      setReference({
        name: uploaded.name,
        url: uploaded.url,
      })
      setPreviewUrl(uploaded.url)
      toast.success('Фото загружено')
""",
        "setPreviewUrl(uploaded.url)",
    )

    replace_once(
        "bot/miniapp.py",
        """from bot.services.media_input_utils import (
    missing_local_upload_sources,
    resolve_local_upload_path,
)
""",
        """from bot.services.media_input_utils import (
    image_source_to_provider_safe_png_url,
    missing_local_upload_sources,
    resolve_local_upload_path,
)
""",
        "    image_source_to_provider_safe_png_url,\n    missing_local_upload_sources,",
    )

    replace_once(
        "bot/miniapp.py",
        """def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    return {
        \"id\": str(reference.id),
        \"kind\": reference.kind,
        \"url\": reference.file_url,
""",
        """def _saved_reference_payload(reference: SavedReference) -> dict[str, Any]:
    file_url = reference.file_url
    if reference.kind == \"image\":
        file_url = image_source_to_provider_safe_png_url(file_url)

    return {
        \"id\": str(reference.id),
        \"kind\": reference.kind,
        \"url\": file_url,
""",
        "file_url = image_source_to_provider_safe_png_url(file_url)",
    )

    replace_once(
        "bot/miniapp.py",
        """    try:
        import io  # noqa: PLC0415

        from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

        with Image.open(io.BytesIO(raw)) as image:
""",
        """    try:
        import io  # noqa: PLC0415

        from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

        try:
            from pillow_heif import register_heif_opener  # noqa: PLC0415
        except ImportError:
            register_heif_opener = None
        if register_heif_opener is not None:
            register_heif_opener()

        with Image.open(io.BytesIO(raw)) as image:
""",
        "from pillow_heif import register_heif_opener  # noqa: PLC0415",
    )

    claude_helper = """

def _build_claude_image_source(image_url: str) -> Dict[str, str]:
    if image_url.startswith(\"data:image/\") and \",\" in image_url:
        header, encoded = image_url.split(\",\", 1)
        media_type = header.removeprefix(\"data:\").split(\";\", 1)[0]
        return {
            \"type\": \"base64\",
            \"media_type\": media_type,
            \"data\": encoded,
        }
    return {\"type\": \"url\", \"url\": image_url}
"""
    replace_once(
        "bot/services/photo_prompt_service.py",
        "\n\nclass PhotoPromptService:\n",
        claude_helper + "\n\nclass PhotoPromptService:\n",
        "def _build_claude_image_source(",
    )
    replace_once(
        "bot/services/photo_prompt_service.py",
        '                            "source": {"type": "url", "url": image_url},\n',
        '                            "source": _build_claude_image_source(image_url),\n',
        '"source": _build_claude_image_source(image_url)',
    )

    test_path = Path("tests/test_mobile_media_upload_contract.py")
    test_text = test_path.read_text(encoding="utf-8")
    if 'assert "setPreviewUrl(uploaded.url)" in workspace' not in test_text:
        test_text = test_text.replace(
            '    assert "photoUploadAttemptRef" in workspace\n',
            '    assert "photoUploadAttemptRef" in workspace\n'
            '    assert "setPreviewUrl(uploaded.url)" in workspace\n',
        )
    if 'assert "_build_claude_image_source" in photo_service' not in test_text:
        test_text = test_text.replace(
            '    assert "image_source_to_analysis_input" in photo_service\n',
            '    assert "image_source_to_analysis_input" in photo_service\n'
            '    assert "_build_claude_image_source" in photo_service\n',
        )
    test_path.write_text(test_text, encoding="utf-8")

    Path(__file__).unlink()


if __name__ == "__main__":
    main()
