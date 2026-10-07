import '@testing-library/jest-dom'
import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PhotoTab } from '@/components/tabs/photo-tab'
import { useApp } from '@/lib/app-context'
import { generateImage, remixFeedItem } from '@/lib/api'
import type { ImageModel, PromptPreset, UploadedFile } from '@/lib/types'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  generateImage: jest.fn(),
  remixFeedItem: jest.fn(),
  uploadFile: jest.fn(),
  sendMiniAppClientLog: jest.fn(),
}))
jest.mock('@/components/forms/model-select', () => ({
  ModelSelect: ({ value }: { value: string }) => <div>{value}</div>,
}))
jest.mock('@/components/forms/ratio-select', () => ({
  RatioSelect: ({ value }: { value: string }) => <div>{value}</div>,
}))
jest.mock('@/components/forms/quality-select', () => ({
  QualitySelect: ({ value }: { value: string }) => <div>{value}</div>,
}))
jest.mock('@/components/result-card', () => ({ ResultCard: () => <div>Result</div> }))

const mockedUseApp = jest.mocked(useApp)
const mockedRemix = jest.mocked(remixFeedItem)

beforeEach(() => jest.resetAllMocks())

const replacements: UploadedFile[] = ['a', 'b'].map((id) => ({
  id, name: `replacement-${id}.png`, type: 'image', size: 0,
  url: `https://example.test/replacement-${id}.png`,
}))
const message = 'Замените недоступный референс перед повтором.'

function mockApp(modelId: string, initialReferences: UploadedFile[] = []) {
  const models: ImageModel[] = [{
    id: modelId, label: modelId, description: 'Edit model', cost: 1,
    ratios: ['1:1'], requires_reference: true, max_references: 9,
  }]
  const addTask = jest.fn()
  const setCredits = jest.fn()
  mockedUseApp.mockImplementation(function useMockApp() {
    const [promptPreset, setPromptPreset] = useState<PromptPreset | null>({
      title: 'Private source repeat', prompt: '', model: modelId,
      sourceFeedGenId: 42, promptHidden: true, initialReferences,
    })
    return {
      state: { mode: 'live', imageModels: models, savedReferences: replacements, user: { credits: 100 } },
      addTask, setCredits, setTaskDetail: jest.fn(), selectTask: jest.fn(), addSavedReference: jest.fn(),
      promptPreset, setPromptPreset,
    } as unknown as ReturnType<typeof useApp>
  })
  return { addTask, setCredits }
}

function acceptedRepeat(model: string): Awaited<ReturnType<typeof remixFeedItem>> {
  return {
    task: { task_id: 'accepted-repeat', type: 'image', model, model_label: model,
      aspect_ratio: '1:1', status: 'pending', created_at: '2026-10-07T00:00:00Z', prompt_preview: '', cost: 1 },
    credits: 99,
  }
}

it.each(['seedream_edit', 'grok_imagine_i2i'])('%s displays server reference validation errors without retrying or using standalone generation', async (modelId) => {
  const { addTask, setCredits } = mockApp(modelId)
  mockedRemix.mockRejectedValue(new Error(message))
  render(<PhotoTab />)

  fireEvent.click(screen.getByRole('button', { name: '2x' }))
  fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

  expect(await screen.findByText(message)).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('button', { name: /Запускаю/i })).not.toBeInTheDocument())
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My next instruction' } })
  expect(screen.getByText(message)).toBeInTheDocument()
  expect(mockedRemix).toHaveBeenCalledTimes(1)
  expect(mockedRemix).toHaveBeenCalledWith(expect.objectContaining({
    genId: 42, model: modelId, prompt: '', references: [],
  }))
  expect(generateImage).not.toHaveBeenCalled()
  expect(addTask).not.toHaveBeenCalled()
  expect(setCredits).not.toHaveBeenCalled()
})

it.each(['seedream_edit', 'grok_imagine_i2i'])('%s preserves the repeat recipe and replacements for a corrected manual retry, then resets after success', async (modelId) => {
  const { addTask, setCredits } = mockApp(modelId, [replacements[0]])
  const accepted = acceptedRepeat(modelId)
  mockedRemix.mockRejectedValueOnce(new Error(message)).mockResolvedValueOnce(accepted)
  render(<PhotoTab />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my changes' } })
  fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

  expect(await screen.findByText(message)).toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('Keep my changes')
  expect(screen.queryByRole('button', { name: replacements[0].name })).not.toBeInTheDocument()
  expect(screen.getByText(replacements[0].name)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Повторить образ/i })).toBeEnabled()
  expect(mockedRemix).toHaveBeenCalledTimes(1)
  expect(mockedRemix).toHaveBeenNthCalledWith(1, expect.objectContaining({
    genId: 42, prompt: 'Keep my changes', references: [replacements[0].url],
  }))

  fireEvent.click(screen.getByRole('button', { name: replacements[1].name }))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my corrected changes' } })
  expect(mockedRemix).toHaveBeenCalledTimes(1)
  expect(screen.getByText(message)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

  await waitFor(() => expect(addTask).toHaveBeenCalledWith(accepted.task))
  expect(mockedRemix).toHaveBeenCalledTimes(2)
  expect(mockedRemix).toHaveBeenNthCalledWith(2, expect.objectContaining({
    genId: 42, prompt: 'Keep my corrected changes', references: replacements.map((item) => item.url),
  }))
  expect(generateImage).not.toHaveBeenCalled()
  expect(setCredits).toHaveBeenCalledWith(99)
  expect(screen.queryByText(message)).not.toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('')
  expect(screen.getByRole('button', { name: /Запустить фото/i })).toBeDisabled()
  for (const file of replacements) expect(screen.getByRole('button', { name: file.name })).toBeInTheDocument()
})

it('reports a partial batch and resets after an accepted item without automatically resubmitting it', async () => {
  const { addTask, setCredits } = mockApp('seedream_edit', [replacements[0]])
  const accepted = acceptedRepeat('seedream_edit')
  mockedRemix.mockResolvedValueOnce(accepted).mockRejectedValueOnce(new Error(message))
  render(<PhotoTab />)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Batch instruction' } })
  fireEvent.click(screen.getByRole('button', { name: '2x' }))
  fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

  expect(await screen.findByText(`Запущено 1 из 2. ${message}`)).toBeInTheDocument()
  expect(addTask).toHaveBeenCalledTimes(1)
  expect(addTask).toHaveBeenCalledWith(accepted.task)
  expect(setCredits).toHaveBeenCalledWith(99)
  expect(screen.getByText('Result')).toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('')
  const launch = screen.getByRole('button', { name: /Запустить фото/i })
  expect(launch).toBeDisabled()
  fireEvent.click(launch)
  expect(mockedRemix).toHaveBeenCalledTimes(2)
  expect(generateImage).not.toHaveBeenCalled()
})
