from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(source: str, old: str, new: str, marker: str) -> str:
    if old not in source:
        raise SystemExit(f"patch marker not found: {marker}")
    return source.replace(old, new, 1)


trends_path = "frontend/miniapp-v0/components/tabs/trends-tab.tsx"
source = read(trends_path)
source = replace_once(
    source,
    "import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'",
    "import { mediaAspectRatio, normalizeMiniAppMediaUrl } from '@/lib/media-url'",
    "trends media import",
)
old_card = '''                    <button type="button" className="block w-full" onClick={() => setPreviewTrend(trend)} aria-label={`Открыть видео ${trend.title}`}>
                      <video
                        src={videoPreviewFrameUrl(trend.preview_url)}
                        muted
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(event) => rememberVideoAspectRatio(trend.id, event.currentTarget)}
                        style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        className="w-full bg-black object-contain"
                      />
                      <span className="absolute inset-0 grid place-items-center bg-black/10"><Film className="h-8 w-8 rounded-full bg-black/55 p-1.5 text-white" /></span>
                    </button>'''
new_card = '''                    <div className="relative w-full">
                      <video
                        src={normalizeMiniAppMediaUrl(trend.preview_url)}
                        controls
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(event) => rememberVideoAspectRatio(trend.id, event.currentTarget)}
                        style={{ aspectRatio: videoAspectRatios[trend.id] || mediaAspectRatio(trend.generation_settings?.ratio) }}
                        className="w-full bg-black object-contain"
                      />
                      <button
                        type="button"
                        onClick={() => setPreviewTrend(trend)}
                        aria-label={`Открыть видео ${trend.title} крупно`}
                        className="absolute right-2 top-2 grid h-9 w-9 place-items-center rounded-full bg-black/60 text-white backdrop-blur"
                      >
                        <Film className="h-4 w-4" />
                      </button>
                    </div>'''
source = replace_once(source, old_card, new_card, "full video trend card")
write(trends_path, source)

runner_path = "frontend/miniapp-v0/components/trend-runner-dialog.tsx"
source = read(runner_path)
source = replace_once(
    source,
    "import { mediaAspectRatio, normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'",
    "import { mediaAspectRatio, normalizeMiniAppMediaUrl } from '@/lib/media-url'",
    "runner media import",
)
source = replace_once(
    source,
    "src={videoPreviewFrameUrl(trend.preview_url)}",
    "src={normalizeMiniAppMediaUrl(trend.preview_url)}",
    "runner full video source",
)
write(runner_path, source)

write(
    "tests/test_trend_full_video_contract.py",
    '''from pathlib import Path\n\n\ndef _read(path: str) -> str:\n    return Path(path).read_text(encoding="utf-8")\n\n\ndef test_video_trend_card_plays_complete_video_in_place():\n    source = _read("frontend/miniapp-v0/components/tabs/trends-tab.tsx")\n    grid = source.split("const renderTrendGrid", 1)[1].split("return (", 1)[1]\n    assert "src={normalizeMiniAppMediaUrl(trend.preview_url)}" in grid\n    assert "controls" in grid\n    assert "videoPreviewFrameUrl(trend.preview_url)" not in grid\n    assert "setPreviewTrend(trend)" in grid\n\n\ndef test_trend_runner_uses_video_from_zero_not_preview_seek_fragment():\n    source = _read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")\n    assert "src={normalizeMiniAppMediaUrl(trend.preview_url)}" in source\n    assert "videoPreviewFrameUrl(trend.preview_url)" not in source\n\n\ndef test_backend_trend_preview_has_no_duration_crop():\n    source = _read("bot/services/trend_preview_service.py")\n    ffmpeg = source.split("def _run_ffmpeg_preview", 1)[1].split(\n        "async def ensure_lightweight_trend_preview_url", 1\n    )[0]\n    assert '\"-t\",' not in ffmpeg\n    assert "TREND_PREVIEW_MAX_SECONDS" not in source\n''',
)
