"""Release regressions for Seedream 5.5 callback loss, repeat and live prices."""

from bot.handlers import generation
from bot.main import _KIE_WATCHDOG_RECOVERY_MODELS


def test_lost_seedream55_callback_is_eligible_for_watchdog_replay():
    assert {"seedream_55", "seedream_55_layers"} <= _KIE_WATCHDOG_RECOVERY_MODELS


def test_repeat_quote_uses_effective_reference_count_and_layer_limit():
    snapshot = {"img_layers_max_images": 7}
    refs = ["https://example.com/a.png", "https://example.com/b.png"]
    assert generation._seedream55_repeat_quote_options(
        "seedream_55", refs, snapshot
    ) == {"reference_count": 2, "max_images": 7}
    assert generation._seedream55_repeat_quote_options(
        "seedream_55_layers", refs[:1], snapshot
    ) == {"reference_count": 1, "max_images": 7}
    # In a repeat setup screen, reserve for the one required image before upload.
    assert generation._seedream55_repeat_quote_options(
        "seedream_55_layers", [], snapshot
    )["reference_count"] == 1
    # Other models must keep their original price function call signature.
    assert generation._seedream55_repeat_quote_options(
        "banana_pro", refs, snapshot
    ) == {}


def test_repeat_launch_preserves_saved_output_options():
    snapshot = {
        "img_output_format": "jpeg",
        "img_background": "opaque",
        "img_layers_max_images": 12,
        "img_layers_text_recognition": True,
    }
    assert generation._seedream55_repeat_launch_options(
        "seedream_55_layers", snapshot
    ) == snapshot
    assert generation._seedream55_repeat_launch_options(
        "seedream_55", snapshot
    ) == snapshot
    assert generation._seedream55_repeat_launch_options(
        "seedream_edit", snapshot
    ) == {}


def test_bootstrap_uses_live_admin_seedream55_prices(monkeypatch):
    from bot import miniapp

    model = next(m for m in miniapp.IMAGE_MODELS if m["id"] == "seedream_55")
    old_price = model["quality_costs"]["2K"]
    monkeypatch.setattr(
        miniapp, "seedream55_quality_prices",
        lambda: {"1K": 5.0, "1.5K": 6.5, "2K": 9.0},
    )
    monkeypatch.setattr(miniapp, "seedream55_input_price", lambda: 2.0)
    refreshed = miniapp._runtime_image_model_metadata(model)
    assert refreshed["quality_costs"]["2K"] == 9.0
    assert refreshed["cost"] == 9.0
    assert refreshed["reference_unit_cost"] == 2.0
    assert model["quality_costs"]["2K"] == old_price
    layers = next(m for m in miniapp.IMAGE_MODELS if m["id"] == "seedream_55_layers")
    assert miniapp._runtime_image_model_metadata(layers)["reference_unit_cost"] == 2.0
    standard = next(m for m in miniapp.IMAGE_MODELS if m["id"] == "banana_pro")
    assert miniapp._runtime_image_model_metadata(standard) is standard
