import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Wan3TrendPublisher } from './wan3-trend-publisher'
import { fetchWan3PrimeTrendRecipe, publishWan3PrimeTrend } from '@/lib/wan3-prime-api'

jest.mock('@/lib/wan3-prime-api', () => ({ fetchWan3PrimeTrendRecipe: jest.fn(), publishWan3PrimeTrend: jest.fn() }))

test('publisher retains all ordered media kinds and submits only explicit replacement keys', async () => {
  ;(fetchWan3PrimeTrendRecipe as jest.Mock).mockResolvedValue({ ok: true, recipe: { scenario: 'edit', seed: 0, audio: false }, slots: [
    { key: 'image:0', kind: 'image', role: 'reference', index: 0, url: 'https://owned.test/subject.png' },
    { key: 'video:0', kind: 'video', role: 'source_video', index: 0, url: 'https://owned.test/source.mp4' },
    { key: 'audio:0', kind: 'audio', role: 'reference', index: 0, url: 'https://owned.test/voice.mp3' },
    { key: 'file:0', kind: 'file', role: 'reference', index: 0, url: 'https://owned.test/script.pdf' },
  ] })
  ;(publishWan3PrimeTrend as jest.Mock).mockResolvedValue({ ok: true, trend_id: 812 })
  render(<Wan3TrendPublisher taskId="wan3_author_original" />)
  fireEvent.click(screen.getByRole('button', { name: 'Создать тренд из Wan' }))
  await screen.findByLabelText('Пользователь заменяет Video1')
  expect(screen.getByLabelText('Пользователь заменяет Image1')).toBeChecked()
  expect(screen.getByLabelText('Пользователь заменяет Video1')).not.toBeChecked()
  expect(screen.getByLabelText('Пользователь заменяет Документ 1')).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Пользователь заменяет Audio1'))
  fireEvent.change(screen.getByLabelText('Название Wan-тренда'), { target: { value: 'Замена персонажа' } })
  fireEvent.change(screen.getByLabelText('Описание Wan-тренда'), { target: { value: 'Добавьте фото и звук' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать Wan-тренд' }))
  await screen.findByText(/Тренд #812 опубликован/)
  await waitFor(() => expect(publishWan3PrimeTrend).toHaveBeenCalledTimes(1))
  expect(publishWan3PrimeTrend).toHaveBeenCalledWith({ task_id: 'wan3_author_original', title: 'Замена персонажа',
    description: 'Добавьте фото и звук', replacement_keys: ['image:0', 'audio:0'] })
})
