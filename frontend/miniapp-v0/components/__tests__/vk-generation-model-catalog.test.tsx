import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { VkGenerationPanel } from '../vk-generation-panel'
import { fetchVkModelCatalog, generateVkImage, uploadVkImage } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkModelCatalog: jest.fn(),
  generateVkImage: jest.fn(),
  repeatVkTrend: jest.fn(),
  uploadVkImage: jest.fn(),
}))

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchVkModelCatalog).mockResolvedValue({
    ok: true,
    photo_models: [{
      id: 'nano_banana_2', label: 'Nano Banana 2',
      ratios: ['9:16', '1:1'], resolutions: ['2K'], max_references: 2,
    }, {
      id: 'gpt_image_2', label: 'GPT Image 2',
      ratios: ['1:1'], resolutions: ['2K','4K'], max_references: 4,
    }],
    video_models: [],
  })
})

test('VK photo form uses native worker model catalog and does not fake unsupported models', async () => {
  render(<VkGenerationPanel onClose={jest.fn()} />)
  expect(await screen.findByRole('option', { name: 'Nano Banana 2' })).toBeInTheDocument()
  expect(screen.queryByRole('option', { name: 'Nano Banana Pro' })).not.toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'GPT Image 2' })).toBeInTheDocument()
  expect(screen.getByLabelText('Качество')).toHaveValue('2K')
  expect(screen.getByLabelText('Формат')).toHaveValue('9:16')
  expect(screen.queryByRole('option', { name: '4K' })).not.toBeInTheDocument()
  expect(fetchVkModelCatalog).toHaveBeenCalled()
})

test('VK model selection follows native reference limits and real quote', async () => {
  jest.mocked(generateVkImage).mockResolvedValue({ ok:true, task_id:0, cost:5, quote_only:true })
  jest.mocked(uploadVkImage).mockResolvedValue('https://neuromixbot.com/uploads/vk-refs/image/2001/' + 'a'.repeat(32) + '.jpg')
  render(<VkGenerationPanel onClose={jest.fn()} />)
  await screen.findByRole('option', { name: 'Nano Banana 2' })
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A test castle' } })
  const files = [1,2,3].map(index => new File(['file'+index], 'ref'+index+'.jpg', {type:'image/jpeg'}))
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('не более 2')
  expect(generateVkImage).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Модель'), { target: { value: 'gpt_image_2' } })
  expect(screen.getByLabelText('Формат')).toHaveValue('1:1')
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 5 🍌' })).toBeInTheDocument()
  expect(jest.mocked(generateVkImage).mock.calls[0][0]).toEqual(expect.objectContaining({
    model:'gpt_image_2',aspect:'1:1',resolution:'2K',reference_photos:expect.any(Array),
  }))
})

test('VK catalog failure never displays guessed provider models or lets client charge', async () => {
  jest.mocked(fetchVkModelCatalog).mockRejectedValue(new Error('Нативный каталог временно недоступен'))
  render(<VkGenerationPanel onClose={jest.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Нативный каталог временно недоступен')
  expect(screen.queryByRole('option', { name: 'Nano Banana Pro' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  expect(generateVkImage).not.toHaveBeenCalled()
})
