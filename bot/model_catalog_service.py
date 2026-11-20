"""One source for native model catalogue and browser-safe capability projection.

Native bootstrap uses native_model_metadata; browser uses its *same* native
metadata and overlays runtime public additions such as Seedance 2.5. No
provider dispatch, billing action, or admin tariff is exposed here.
"""
from __future__ import annotations

from bot.kling4_tariff import kling4_public_enabled

# Never serialize pricing/internal fields on the independent-browser read
# surface. The authoritative quote still belongs to the relevant paid service.
_BROWSER_PUBLIC_FIELDS = frozenset({
    "id", "label", "description", "ratios", "durations", "qualities",
    "requires_reference", "supports", "max_references",
    "max_image_references", "max_video_references", "max_audio_references",
    "seedance25_resolutions", "seedance25_output_formats",
    "seedance25_scenarios", "supports_generate_audio",
    "supports_return_last_frame", "supports_web_search",
    "supports_nsfw_checker", "supports_auto_duration",
    "camera_control_via_prompt", "supports_layers",
    "supports_output_format", "supports_background",
})


def native_model_metadata(
    *, tariff: str, is_admin: bool, kling4_public=None, kling4_entry=None,
) -> dict:
    """Build original Telegram Mini App catalogue with live configured rates."""
    from bot import miniapp

    creator_tariff_display = miniapp.creator_tariff_display
    preset_manager = miniapp.preset_manager
    _runtime_image_model_metadata = miniapp._runtime_image_model_metadata
    IMAGE_MODELS = miniapp.IMAGE_MODELS
    VIDEO_MODELS = miniapp.VIDEO_MODELS
    from bot.kling4_api import catalog_entry as official_kling4_catalog
    kling4_catalog_entry = kling4_entry or official_kling4_catalog
    public_flag = kling4_public or miniapp.kling4_public_enabled
    return {
            "image_models": [
                creator_tariff_display.price_image_model_metadata(
                    item,
                    tariff=tariff,
                )
                for item in (_runtime_image_model_metadata(model) for model in IMAGE_MODELS)
            ],
            "video_models": [
                creator_tariff_display.price_video_model_metadata({
                    **item,
                    "costs": {
                        str(duration): preset_manager.get_video_cost(
                            item["id"], duration
                        )
                        for duration in item["durations"]
                    },
                    "quality_costs": preset_manager.get_video_quality_costs(
                        item["id"]
                    ),
                    **(
                        {
                            "omni_audio_cost": preset_manager.get_video_cost(
                                "gemini_omni_audio", 6
                            ),
                            "omni_character_cost": preset_manager.get_video_cost(
                                "gemini_omni_character", 6
                            ),
                        }
                        if item["id"] == "gemini_omni"
                        else {}
                    ),
                }, tariff=tariff)
                for item in VIDEO_MODELS
            ] + (
                [kling4_catalog_entry()]
                if is_admin or public_flag()
                else []
            )
    }


def _browser_public_model(item: dict, *, kind: str) -> dict:
    return {
        key: value for key, value in item.items()
        if key in _BROWSER_PUBLIC_FIELDS
    } | {
        "kind": kind,
        "available_in_telegram": True,
        # This is a read-only inventory. Web billing needs a completed
        # shared-account wallet and task cutover, not a forged TG identity.
        "web_generate_enabled": False,
    }


def public_browser_catalog() -> dict:
    """Return public native model options to signed independent browser users.

    Runtime-installed extensions are included from their existing native
    registration. Admin-only Kling4 is not exposed when rollout is disabled.
    Model availability is not authorization to initiate a paid web task.
    """
    from bot.handlers import generation as generation_module
    from bot.handlers import seedance_25_public_release as seedance_public

    native = native_model_metadata(
        tariff="standard", is_admin=False, kling4_public=kling4_public_enabled,
    )
    images = [
        _browser_public_model(entry, kind="image")
        for entry in native["image_models"]
    ]
    videos = [
        _browser_public_model(entry, kind="video")
        for entry in native["video_models"]
    ]
    if getattr(generation_module, "_seedance_25_public_release_installed", False):
        public_entry = seedance_public._public_model_meta(tariff="standard")
        videos = [entry for entry in videos if entry["id"] != public_entry["id"]]
        videos.append(_browser_public_model(public_entry, kind="video"))
    return {
        "catalog_scope": "read_only",
        "web_generate_enabled": False,
        "image_models": images,
        "video_models": videos,
    }
