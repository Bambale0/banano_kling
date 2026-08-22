from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(source: str, old: str, new: str, marker: str) -> str:
    if old not in source:
        raise SystemExit(f"patch marker not found: {marker}")
    return source.replace(old, new, 1)


def patch_trend_preview() -> None:
    path = "bot/services/trend_preview_service.py"
    source = read(path)
    source = replace_once(
        source,
        'TREND_PREVIEW_MAX_SECONDS = int(os.getenv("TREND_PREVIEW_MAX_SECONDS", "6"))\n',
        'TREND_PREVIEW_VERSION = "full-v2"\n',
        "trend preview max seconds",
    )
    source = replace_once(
        source,
        'payload = f"{public_url}|{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"',
        'payload = f"{TREND_PREVIEW_VERSION}|{public_url}|{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"',
        "trend local cache payload",
    )
    source = replace_once(
        source,
        'payload = f"{public_url}|{source}"',
        'payload = f"{TREND_PREVIEW_VERSION}|{public_url}|{source}"',
        "trend remote cache payload",
    )
    source = replace_once(
        source,
        "    max_seconds = _safe_int(TREND_PREVIEW_MAX_SECONDS, minimum=1, maximum=15)\n",
        "",
        "trend max seconds normalization",
    )
    source = replace_once(
        source,
        '        "-t",\n        str(max_seconds),\n',
        "",
        "ffmpeg duration crop",
    )
    source = replace_once(
        source,
        "    subprocess.run(command, check=True, timeout=60)\n",
        "    subprocess.run(command, check=True, timeout=120)\n",
        "ffmpeg timeout",
    )
    write(path, source)


def patch_trend_runner() -> None:
    path = "frontend/miniapp-v0/components/trend-runner-dialog.tsx"
    source = read(path)
    source = replace_once(
        source,
        "import type { PromptItem } from '@/lib/types'",
        "import type { PromptItem, UploadedFile } from '@/lib/types'",
        "trend runner UploadedFile import",
    )
    source = replace_once(
        source,
        "  const [previewUrls, setPreviewUrls] = useState<string[]>([])\n",
        "  const [previewUrls, setPreviewUrls] = useState<string[]>([])\n  const [uploadedReferences, setUploadedReferences] = useState<UploadedFile[]>([])\n",
        "trend runner uploaded state",
    )
    source = replace_once(
        source,
        "    clearPreviews()\n    if (inputRef.current) inputRef.current.value = ''\n",
        "    clearPreviews()\n    setUploadedReferences([])\n    if (inputRef.current) inputRef.current.value = ''\n",
        "trend runner reset state",
    )

    start = source.index("  const handlePhotos = async (selectedFiles: File[]) => {")
    end = source.index("\n\n  return (", start)
    handlers = '''  const handlePhotos = async (selectedFiles: File[]) => {
    if (!trend || busy || !selectedFiles.length) return
    if (uploadedReferences.length + selectedFiles.length > MAX_REFERENCES) {
      setPhase('error')
      setError(`Можно загрузить максимум ${MAX_REFERENCES} фото`)
      return
    }

    const invalidFile = selectedFiles.find((file) => {
      const extension = file.name.split('.').pop()?.toLowerCase() || ''
      return !file.type.startsWith('image/') && !IMAGE_EXTENSIONS.has(extension)
    })
    if (invalidFile) {
      setPhase('error')
      setError(`Файл «${invalidFile.name}» не является изображением`)
      return
    }

    const localPreviews = selectedFiles.map((file) => URL.createObjectURL(file))
    previewRefs.current = [...previewRefs.current, ...localPreviews]
    setPreviewUrls((current) => [...current, ...localPreviews])
    setError(null)
    setPhase('uploading')

    try {
      const uploaded = await Promise.all(
        selectedFiles.map((file) => uploadFile('image_reference', file)),
      )
      for (const reference of uploaded) addSavedReference(reference)
      setUploadedReferences((current) => [...current, ...uploaded])
      setPhase('idle')
    } catch (cause) {
      for (const previewUrl of localPreviews) URL.revokeObjectURL(previewUrl)
      previewRefs.current = previewRefs.current.filter((url) => !localPreviews.includes(url))
      setPreviewUrls((current) => current.filter((url) => !localPreviews.includes(url)))
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить фото')
    }
  }

  const handleGenerate = async () => {
    if (!trend || busy || !uploadedReferences.length) return
    setError(null)
    setPhase('generating')
    try {
      const result = await runTrend(
        trend.id,
        uploadedReferences.map((reference) => reference.url),
      )
      addTask(result.task)
      setCredits(result.credits)
      if (result.detail) setTaskDetail(result.detail)
      selectTask(result.task)
      onOpenChange(false)
    } catch (cause) {
      setPhase('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось запустить тренд')
    }
  }'''
    source = source[:start] + handlers + source[end:]

    source = replace_once(
        source,
        "            После загрузки генерация начнётся сразу. Модель, промпт, формат,\n            качество и остальные параметры уже настроены администратором.",
        "            Добавьте все нужные фото — можно по одному или несколькими заходами.\n            Генерация начнётся только после нажатия кнопки «Сгенерировать».",
        "trend runner explanatory copy",
    )
    source = replace_once(
        source,
        "                : phase === 'error'\n                  ? 'Выбрать фото заново'\n                  : 'Выбрать фото'}",
        "                : phase === 'error'\n                  ? 'Добавить фото ещё раз'\n                  : uploadedReferences.length\n                    ? 'Добавить ещё фото'\n                    : 'Выбрать фото'}",
        "trend runner picker label",
    )
    source = replace_once(
        source,
        "              До {MAX_REFERENCES} изображений\n",
        "              Выбрано {uploadedReferences.length} из {MAX_REFERENCES}\n",
        "trend runner selected count",
    )

    close_button = '''        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          Закрыть
        </Button>'''
    generate_and_close = '''        <Button
          type="button"
          disabled={busy || uploadedReferences.length === 0}
          onClick={() => void handleGenerate()}
        >
          {phase === 'generating' ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {phase === 'generating'
            ? 'Генерирую…'
            : `Сгенерировать · ${uploadedReferences.length} фото`}
        </Button>

        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => onOpenChange(false)}
        >
          Закрыть
        </Button>'''
    source = replace_once(
        source,
        close_button,
        generate_and_close,
        "trend runner generate button",
    )
    write(path, source)


def patch_profile_video() -> None:
    path = "frontend/miniapp-v0/components/tabs/profile-tab.tsx"
    source = read(path)
    source = replace_once(
        source,
        "import { cn, isHttpUrl } from '@/lib/utils'\n",
        "import { cn, isHttpUrl } from '@/lib/utils'\nimport { normalizeMiniAppMediaUrl, videoPreviewFrameUrl } from '@/lib/media-url'\n",
        "profile media-url import",
    )

    marker = "\nfunction profileInteractionsEnabled(item: FeedItem | null | undefined) {"
    if marker not in source:
        raise SystemExit("patch marker not found: profile component insertion")
    video_component = '''
function ProfileFeedVideo({ src, blurred, onError }: {
  src: string
  blurred?: boolean
  onError: () => void
}) {
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    setLoaded(false)
  }, [src])

  return (
    <>
      {!loaded ? (
        <span className="absolute inset-0 animate-pulse bg-gradient-to-br from-secondary via-muted to-secondary/70" />
      ) : null}
      <video
        src={videoPreviewFrameUrl(src)}
        muted
        playsInline
        preload="metadata"
        onLoadedData={() => setLoaded(true)}
        onLoadedMetadata={() => setLoaded(true)}
        onError={onError}
        className={cn(
          'relative z-10 h-full w-full object-cover transition-all duration-500 group-hover:scale-[1.04]',
          loaded ? 'opacity-100' : 'opacity-0',
          blurred && 'scale-110 blur-xl'
        )}
      />
    </>
  )
}
'''
    source = source.replace(marker, video_component + marker, 1)

    old_grid = '''                  item.gen_type === 'video' ? (
                    isHttpUrl(item.preview_url) ? (
                      <img
                        src={item.preview_url}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        onError={() => handleMediaError(item)}
                        className={cn(
                          'h-full w-full object-cover opacity-80 transition-all duration-500 group-hover:scale-[1.04]',
                          item.feed_blurred && !revealedIds.has(item.id) && 'scale-110 blur-xl'
                        )}
                      />
                    ) : (
                      <span className="flex h-full w-full items-center justify-center text-muted-foreground">
                        <Play className="h-6 w-6 fill-current" />
                      </span>
                    )
                  ) : ('''
    new_grid = '''                  item.gen_type === 'video' ? (
                    <ProfileFeedVideo
                      src={item.preview_url || item.result_url}
                      blurred={item.feed_blurred && !revealedIds.has(item.id)}
                      onError={() => handleMediaError(item)}
                    />
                  ) : ('''
    source = replace_once(source, old_grid, new_grid, "profile video tile")

    source = replace_once(
        source,
        '''                src={previewItem.result_url}
                className="max-h-full w-auto max-w-full object-contain"
                controls
                autoPlay
                playsInline
                onError={() => {
                  handleMediaError(previewItem)
                  setPreviewItem(null)
                }}''',
        '''                src={normalizeMiniAppMediaUrl(previewItem.result_url)}
                className="max-h-full w-auto max-w-full object-contain"
                controls
                autoPlay
                muted
                playsInline
                preload="metadata"
                onError={() => handleMediaError(previewItem)}''',
        "profile full-screen video",
    )
    write(path, source)


def patch_video_references() -> None:
    path = "frontend/miniapp-v0/components/forms/video-generator-form.tsx"
    source = read(path)
    source = replace_once(
        source,
        "      videoReferences: isOmniVideo || selectedScenario === 'video' ? videoReferences.map(r => r.url) : [],",
        "      videoReferences: isOmniVideo || (model?.max_video_references ?? 0) > 0 ? videoReferences.map(r => r.url) : [],",
        "video reference forwarding",
    )
    write(path, source)


def patch_default_trends_tab() -> None:
    path = "frontend/miniapp-v0/lib/app-context.tsx"
    source = read(path)
    source = replace_once(
        source,
        "  const [activeTab, setActiveTabState] = useState(0)",
        "  const [activeTab, setActiveTabState] = useState(5)",
        "default active tab",
    )
    source = source.replace(
        "    setActiveTabState(0)\n    setState(createLockedState(message, false))",
        "    setActiveTabState(5)\n    setState(createLockedState(message, false))",
        1,
    )
    write(path, source)


def write_regression_contract() -> None:
    write(
        "tests/test_miniapp_four_fixes_contract.py",
        '''from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_trend_preview_keeps_full_duration_and_invalidates_old_clip_cache():
    source = _read("bot/services/trend_preview_service.py")
    ffmpeg = source.split("def _run_ffmpeg_preview", 1)[1].split(
        "async def ensure_lightweight_trend_preview_url", 1
    )[0]
    assert 'TREND_PREVIEW_VERSION = "full-v2"' in source
    assert '"-t",' not in ffmpeg
    assert "TREND_PREVIEW_MAX_SECONDS" not in source


def test_trend_photo_selection_does_not_auto_generate():
    source = _read("frontend/miniapp-v0/components/trend-runner-dialog.tsx")
    upload_handler = source.split("const handlePhotos", 1)[1].split(
        "const handleGenerate", 1
    )[0]
    generate_handler = source.split("const handleGenerate", 1)[1].split("return (", 1)[0]
    assert "runTrend(" not in upload_handler
    assert "runTrend(" in generate_handler
    assert "setUploadedReferences((current) => [...current, ...uploaded])" in upload_handler
    assert "Сгенерировать · ${uploadedReferences.length} фото" in source


def test_profile_video_grid_uses_video_element_and_fullscreen_normalizes_url():
    source = _read("frontend/miniapp-v0/components/tabs/profile-tab.tsx")
    component = source.split("function ProfileFeedVideo", 1)[1].split(
        "function profileInteractionsEnabled", 1
    )[0]
    assert "<video" in component
    assert "<img" not in component
    assert 'preload="metadata"' in component
    assert "videoPreviewFrameUrl(src)" in component
    assert "normalizeMiniAppMediaUrl(previewItem.result_url)" in source


def test_capable_video_models_keep_selected_video_references():
    source = _read("frontend/miniapp-v0/components/forms/video-generator-form.tsx")
    assert (
        "videoReferences: isOmniVideo || (model?.max_video_references ?? 0) > 0 "
        "? videoReferences.map(r => r.url) : []"
    ) in source


def test_trends_are_default_miniapp_tab():
    source = _read("frontend/miniapp-v0/lib/app-context.tsx")
    assert "const [activeTab, setActiveTabState] = useState(5)" in source
    assert "setTrendToRun(prompt)" in source
    assert "setActiveTabState(5)" in source
''',
    )


def main() -> None:
    patch_trend_preview()
    patch_trend_runner()
    patch_profile_video()
    patch_video_references()
    patch_default_trends_tab()
    write_regression_contract()
    print("Applied Mini App four-fix patch successfully")


if __name__ == "__main__":
    main()
