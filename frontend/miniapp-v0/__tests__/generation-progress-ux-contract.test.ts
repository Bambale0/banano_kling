import fs from 'node:fs'
import path from 'node:path'

const read = (file: string) => fs.readFileSync(path.join(process.cwd(), file), 'utf8')

describe('generation progress UX contract', () => {
  it('renders a dedicated animated pending state for every task type', () => {
    const taskCard = read('components/task-card.tsx')
    const visual = read('components/generation-pending-visual.tsx')

    expect(taskCard).toContain("task.status === 'pending'")
    expect(taskCard).toContain('<GenerationPendingVisual type={task.type} />')
    expect(taskCard).toContain("label: 'Генерируется'")

    expect(visual).toContain('useReducedMotion()')
    expect(visual).toContain("type === 'audio'")
    expect(visual).toContain("type === 'character'")
    expect(visual).toContain("animate={reduceMotion ? undefined")
    expect(visual).toContain('Создаём результат…')
  })
})
