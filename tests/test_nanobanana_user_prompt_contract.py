from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nanobanana_route_sends_user_prompt_to_provider() -> None:
    generation_source = (ROOT / "bot/handlers/generation.py").read_text(
        encoding="utf-8"
    )

    assert "banana_provider_prompt = prompt" in generation_source
    assert "banana_provider_prompt = effective_prompt or prompt" not in generation_source
