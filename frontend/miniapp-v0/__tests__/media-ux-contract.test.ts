import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('Mini App media UX contracts', () => {
  it('preserves configured vertical ratio and iOS first-frame previews for trends', () => {
    const source = read('components/tabs/trends-tab.tsx')
    expect(source).toContain('mediaAspectRatio(trend.generation_settings?.ratio)')
    expect(source).toContain('videoPreviewFrameUrl(trend.preview_url)')
    expect(source).toContain('const posterUrl = trend.preview_poster_url')
    expect(source).toContain('poster={posterUrl || undefined}')
    expect(source).toContain('!videoPreviewReady[trend.id]')
    expect(source).toContain('onLoadedData={() => {')
    expect(source).toContain('setVideoCardReady(trend.id, true)')
    expect(source).toContain('setVideoCardFailed(trend.id, true)')
    expect(source).toContain('!posterUrl && videoPreviewFailed[trend.id]')
    expect(source).toContain('autoPlay')
    expect(source).toContain('loop')
    expect(source).toContain('preload="auto"')
    expect(source).toContain('normalizeMiniAppMediaUrl(previewTrend.preview_url)')
    expect(source).toContain('poster={previewTrend.preview_poster_url ? normalizeMiniAppMediaUrl(previewTrend.preview_poster_url) : undefined}')
    expect(source).toContain('updatePromptPreview(editingTrend.id, finalPreviewUrl)')
    expect(source).toContain('aria-label="Редактировать тренд"')
    expect(source).toContain('<span className="truncate">Редактировать</span>')
    expect(source).toContain('Загрузите новый preview, тренд останется тем же.')

    const api = read('lib/api.ts')
    expect(api).toContain("postJson<{ ok: true; prompt: PromptItem }>('admin/prompts/update-preview'")

    const runner = read('components/trend-runner-dialog.tsx')
    expect(runner).toContain('const [trendPreviewFailed, setTrendPreviewFailed] = useState(false)')
    expect(runner).toContain('onError={() => setTrendPreviewFailed(true)}')
    expect(runner).toContain('trendPreviewFailed && !trend.preview_poster_url')
  })

  it('uses lightweight thumbnails for public feed image references', () => {
    const source = read('components/tabs/feed-tab.tsx')
    expect(source).toContain('feedReferenceImageThumbnailUrl(previewItem.id, index)')
    expect(source).toContain('feedReferenceImageFullUrl(previewItem.id, index)')
    expect(source).toContain('loading="lazy"')
    expect(source).toContain('decoding="async"')
    expect(source).not.toContain('<img src={normalizeMiniAppMediaUrl(reference.url)}')
    expect(source).toContain('item.references_hidden || item.feed_references_visible === false')

    const media = read('lib/media-url.ts')
    expect(media).toContain('/thumbnail`')
    expect(media).toContain('/full`')
  })

  it('normalizes old upload hosts onto the live Mini App origin', () => {
    const source = read('lib/media-url.ts')
    expect(source).toContain("'tanyapi.chillcreative.ru'")
    expect(source).toContain("url.pathname.startsWith('/uploads/')")
    expect(source).toContain("url.hash = 't=0.001'")
  })
})
