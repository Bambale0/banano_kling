import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('Mini App Studio cleanup contract', () => {
  it('does not expose generation history in Studio', () => {
    const studio = read('components/tabs/studio-tab.tsx')

    expect(studio).not.toContain('TaskHistoryList')
    expect(studio).not.toContain('Ваши работы')
    expect(studio).toContain('Готовые работы остаются в чате с ботом')
  })

  it('keeps the reusable saved-reference picker', () => {
    const uploadArea = read('components/forms/upload-area.tsx')

    expect(uploadArea).toContain('availableLibraryFiles')
    expect(uploadArea).toContain('handleAddFromLibrary')
    expect(uploadArea).toContain('Можно добавить без повторной загрузки')
    expect(uploadArea).toContain("libraryLabel = 'Сохранённые референсы'")
    expect(uploadArea).toContain('file.preview_url || file.url')
    expect(uploadArea).toContain("reference-preview-failed")
    expect(uploadArea).toContain('files.map((file)')
  })
})
