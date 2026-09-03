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

  it('does not expose the persistent saved-reference gallery', () => {
    const uploadArea = read('components/forms/upload-area.tsx')

    expect(uploadArea).not.toContain('availableLibraryFiles')
    expect(uploadArea).not.toContain('handleAddFromLibrary')
    expect(uploadArea).not.toContain('Можно добавить без повторной загрузки')
    expect(uploadArea).toContain('files.map((file)')
  })
})
