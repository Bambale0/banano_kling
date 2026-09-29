import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { Seedance25PublicForm } from './seedance25-public-form'
import { Seedance25AdminForm } from './seedance25-admin-form'

jest.mock('@/lib/api', () => ({ uploadFile: jest.fn() }))

describe.each(['public', 'admin'])('Seedance 2.5 %s prompt limit', (surface) => {
  it('allows 30000 Unicode characters and blocks 30001', () => {
    const { container } = render(surface === 'public'
      ? <Seedance25PublicForm credits={100000} isAdmin={false} />
      : <Seedance25AdminForm />)
    const prompt = container.querySelector('textarea[placeholder*="промпт"], textarea[placeholder*="Опишите"]')
    expect(prompt).not.toBeNull()
    const submit = screen.getByRole('button', { name: /Создать видео|Запустить Seedance/ })
    for (const length of [5001, 30000, 30001]) {
      fireEvent.change(prompt!, { target: { value: 'я'.repeat(length - 1) + '🎬' } })
      expect(screen.getByText(`${length}/30000`)).toBeInTheDocument()
      if (length > 30000) expect(submit).toBeDisabled()
      else expect(submit).toBeEnabled()
    }
  })
})
