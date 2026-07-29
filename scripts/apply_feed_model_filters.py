from __future__ import annotations

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one anchor, got {count}: {old[:180]!r}")
    write(path, text.replace(old, new, 1))


def patch_api() -> None:
    path = "frontend/miniapp-v0/lib/api.ts"
    replace_once(
        path,
        """export async function fetchFeed(payload: {
  source?: 'recent' | 'top_day' | 'top'
  limit?: number
  offset?: number
} = {}): Promise<FeedItem[]> {""",
        """export async function fetchFeed(payload: {
  source?: 'recent' | 'top_day' | 'top'
  model?: string
  limit?: number
  offset?: number
} = {}): Promise<FeedItem[]> {""",
    )
    replace_once(
        path,
        """    source: payload.source || 'recent',
    limit: payload.limit ?? 80,""",
        """    source: payload.source || 'recent',
    model: payload.model || 'banana_pro',
    limit: payload.limit ?? 80,""",
    )


def patch_feed_tab() -> None:
    path = "frontend/miniapp-v0/components/tabs/feed-tab.tsx"
    replace_once(
        path,
        """  const [source, setSource] = useState<(typeof sources)[number]['id']>('recent')
  const [items, setItems] = useState<FeedItem[]>([])""",
        """  const [source, setSource] = useState<(typeof sources)[number]['id']>('recent')
  const [model, setModel] = useState('banana_pro')
  const [items, setItems] = useState<FeedItem[]>([])""",
    )
    replace_once(
        path,
        """  const isLive = state.mode === 'live'
  const visibleItems = useMemo(""",
        """  const isLive = state.mode === 'live'
  const modelTabs = useMemo(() => {
    const byId = new Map<string, { id: string; label: string }>()
    for (const item of [...state.imageModels, ...state.videoModels]) {
      const id = String(item.id || '').trim()
      if (!id || byId.has(id)) continue
      byId.set(id, {
        id,
        label: String(item.label || id).replace('🔥 НОВИНКА', '').trim(),
      })
    }
    const banana = byId.get('banana_pro') || { id: 'banana_pro', label: 'Nano Banana Pro' }
    return [banana, ...Array.from(byId.values()).filter((item) => item.id !== 'banana_pro')]
  }, [state.imageModels, state.videoModels])
  const selectedModelLabel = modelTabs.find((item) => item.id === model)?.label || model
  const visibleItems = useMemo(""",
    )
    replace_once(
        path,
        """        const feed = await fetchFeed({ source, limit: FEED_PAGE_SIZE, offset: 0 })""",
        """        const feed = await fetchFeed({ source, model, limit: FEED_PAGE_SIZE, offset: 0 })""",
    )
    replace_once(
        path,
        """  }, [isLive, source])""",
        """  }, [isLive, source, model])""",
    )
    replace_once(
        path,
        """      const feed = await fetchFeed({ source, limit: FEED_PAGE_SIZE, offset: items.length })""",
        """      const feed = await fetchFeed({ source, model, limit: FEED_PAGE_SIZE, offset: items.length })""",
    )
    replace_once(
        path,
        """      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((item) => (""",
        """      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Нейросеть</p>
          <span className="truncate text-xs text-gold">{selectedModelLabel}</span>
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {modelTabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                setModel(item.id)
                setItems([])
                setHasMore(false)
              }}
              className={cn(
                'shrink-0 rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
                model === item.id
                  ? 'border-cyan/50 bg-cyan/15 text-cyan'
                  : 'border-border/50 bg-secondary/50 text-muted-foreground'
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1">
        {sources.map((item) => (""",
    )


def patch_bot_description() -> None:
    path = "bot/main.py"
    replace_once(
        path,
        """    try:
        for language_code in USER_BOT_COMMAND_LANGUAGES:
            await bot.set_my_short_description(
                "Mini App + текстовый бот. Для обычного режима нажмите /start.",
                language_code=language_code,
            )
            await bot.set_my_description(
                "Нейросети для фото и видео. Есть два режима: Mini App и обычный текстовый бот.\n\n"
                "• Mini App — быстрый визуальный интерфейс\n"
                "• /start — текстовое меню и пошаговый режим прямо в чате",
                language_code=language_code,
            )
        logger.info("Registered bot descriptions for Mini App and text mode")
    except Exception:
        logger.exception("Failed to register bot descriptions")""",
        """    try:
        for language_code in USER_BOT_COMMAND_LANGUAGES:
            await bot.set_my_short_description("", language_code=language_code)
            await bot.set_my_description("", language_code=language_code)
        logger.info("Cleared Telegram bot profile descriptions")
    except Exception:
        logger.exception("Failed to clear Telegram bot descriptions")""",
    )


def main() -> None:
    patch_api()
    patch_feed_tab()
    patch_bot_description()


if __name__ == "__main__":
    main()
