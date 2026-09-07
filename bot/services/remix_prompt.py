from __future__ import annotations

from typing import Any


def _prompt_text(value: Any) -> str:
    return str(value or "").strip()


def compose_feed_remix_prompt(source_prompt: Any, user_changes: Any) -> str:
    """Keep the source prompt as the base and layer user remix changes on top.

    Feed/profile repeats must never let the editable Mini App field replace the
    author's source prompt. The client sends only the user's requested changes;
    this function combines them server-side so hidden prompts stay private.

    The ``source in changes`` compatibility branch handles a short rollout
    window where an older client may still submit the source prompt inside the
    editable field.
    """

    source = _prompt_text(source_prompt)
    changes = _prompt_text(user_changes)

    if not source:
        return changes
    if not changes or changes == source:
        return source

    if source in changes:
        changes = changes.replace(source, " ", 1).strip()
        if not changes:
            return source

    return (
        f"{source}\n\n"
        "USER CHANGES: Apply only the requested changes below. "
        "Keep everything else from the base prompt unchanged unless the user explicitly overrides it.\n"
        f"{changes}"
    )
