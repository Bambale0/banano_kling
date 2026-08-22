import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('Task detail UX contracts', () => {
  it('does not render the prompt copy button for hidden prompts', () => {
    const source = read('components/task-detail-panel.tsx')

    expect(source).toContain('const canCopyPrompt = Boolean(taskDetail?.prompt && !taskDetail?.prompt_hidden)')
    expect(source).toContain('{canCopyPrompt ? (')
    expect(source).not.toContain('disabled={!taskDetail.prompt || taskDetail.prompt_hidden}')
  })
})
