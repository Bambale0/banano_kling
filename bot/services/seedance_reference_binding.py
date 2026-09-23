"""Canonical Seedance multimodal reference tag binding.

Seedance prompts bind uploaded media by typed aliases such as ``@Image1`` and
``@Video1``. User/admin prompts have historically used mixed case, whitespace,
or one combined ordinal across all uploaded media. Normalize those variants at
the provider boundary so every caller gets the same deterministic binding.
"""

from __future__ import annotations

import re

_TAG_RE = re.compile(
    r"@\s*(?P<kind>image|img|video|audio)\s*[_-]?\s*(?P<index>\d+)(?!\w)",
    re.IGNORECASE,
)


def canonicalize_seedance_reference_tags(
    prompt: str,
    *,
    image_count: int = 0,
    video_count: int = 0,
    audio_count: int = 0,
) -> str:
    """Return prompt with reference mentions canonicalized to Seedance aliases.

    Besides case/spacing normalization, repair the legacy combined-ordinal form
    used by some trend prompts. Example: with three images and one video,
    ``@IMAGE 4`` refers to the fourth uploaded asset and becomes ``@Video1``.
    """

    text = str(prompt or "")
    images = max(0, int(image_count))
    videos = max(0, int(video_count))
    audios = max(0, int(audio_count))

    def replace(match: re.Match[str]) -> str:
        kind = match.group("kind").lower()
        index = int(match.group("index"))

        if kind in {"image", "img"}:
            if index > images and index > 0:
                overflow = index - images
                if 1 <= overflow <= videos:
                    return f"@Video{overflow}"
                overflow -= videos
                if 1 <= overflow <= audios:
                    return f"@Audio{overflow}"
            return f"@Image{index}"

        if kind == "video":
            return f"@Video{index}"

        return f"@Audio{index}"

    return _TAG_RE.sub(replace, text)
