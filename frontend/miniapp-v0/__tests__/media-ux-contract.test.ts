import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('Mini App media UX contracts', () => {
  it('preserves configured vertical ratio and iOS first-frame previews for trends', () => {
    const source = read('components/tabs/trends-tab.tsx')
    expect(source).toContain('mediaAspectRatio(trend.generation_settings?.ratio)')
    expect(source).toContain('videoPreviewFrameUrl(trend.preview_url)')
    expect(source).toContain('normalizeMiniAppMediaUrl(previewTrend.preview_url)')
  })

  it('lets users inspect public feed references instead of dead black thumbnails', () => {
    const source = read('components/tabs/feed-tab.tsx')
    expect(source).toContain('setReferencePreview(reference)')
    expect(source).toContain('videoPreviewFrameUrl(reference.url)')
    expect(source).toContain('normalizeMiniAppMediaUrl(referencePreview.url)')
    expect(source).toContain('item.references_hidden || item.feed_references_visible === false')
  })

  it('normalizes old upload hosts onto the live Mini App origin', () => {
    const source = read('lib/media-url.ts')
    expect(source).toContain("'tanyapi.chillcreative.ru'")
    expect(source).toContain("url.pathname.startsWith('/uploads/')")
    expect(source).toContain("url.hash = 't=0.001'")
  })
})
