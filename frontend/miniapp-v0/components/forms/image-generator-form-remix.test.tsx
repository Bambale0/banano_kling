import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

jest.mock('@/components/forms/model-select', () => ({
  ModelSelect: ({ value }: { value: string }) => <div data-testid="model">{value}</div>,
}))
jest.mock('@/components/forms/ratio-select', () => ({
  RatioSelect: ({ value }: { value: string }) => <div data-testid="ratio">{value}</div>,
}))
jest.mock('@/components/forms/quality-select', () => ({
  QualitySelect: ({ value }: { value: string }) => <div data-testid="quality">{value}</div>,
}))
jest.mock('@/components/forms/upload-area', () => ({
  UploadArea: () => <div data-testid="upload-area" />,
}))

import { ImageGeneratorForm } from '@/components/forms/image-generator-form'
import type { ImageModel, PromptPreset } from '@/lib/types'

const models: ImageModel[] = [{
  id: 'test_image',
  label: 'Test image',
  description: 'test',
  cost: 1,
  ratios: ['1:1'],
  requires_reference: false,
  max_references: 4,
}]

const remixPreset: PromptPreset = {
  promptId: null,
  title: 'Повторить образ из ленты',
  prompt: 'AUTHOR SOURCE PROMPT MUST STAY SERVER-SIDE',
  model: 'test_image',
  ratio: '1:1',
  sourceFeedGenId: 42,
}

describe('ImageGeneratorForm feed remix', () => {
  it('uses the textarea only for user changes and does not expose the author prompt as editable text', async () => {
    const onSubmit = jest.fn().mockResolvedValue(true)
    const consumed = jest.fn()

    render(
      <ImageGeneratorForm
        models={models}
        onSubmit={onSubmit}
        promptPreset={remixPreset}
        onPromptPresetConsumed={consumed}
        isSubmitting={false}
        credits={100}
      />,
    )

    await waitFor(() => expect(consumed).toHaveBeenCalled())

    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('')
    expect(screen.getByText(/Исходный промпт автора сохранится автоматически/i)).toBeInTheDocument()

    fireEvent.change(textarea, { target: { value: 'Сделай волосы блонд' } })
    fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      sourceFeedGenId: 42,
      prompt: 'Сделай волосы блонд',
    }))
  })
})


describe.each(['seedream_edit', 'grok_imagine_i2i'])('%s server-owned repeat references', (modelId) => {
  const editModels: ImageModel[] = [{ ...models[0], id: modelId, requires_reference: true }]
  const privateRepeat: PromptPreset = {
    ...remixPreset,
    model: modelId,
    promptHidden: true,
    initialReferences: [],
  }

  it('submits an all-fixed repeat without exposing or requiring private reference URLs', async () => {
    const onSubmit = jest.fn().mockResolvedValue(true)
    render(<ImageGeneratorForm models={editModels} onSubmit={onSubmit} promptPreset={privateRepeat} isSubmitting={false} credits={100} />)

    const repeat = screen.getByRole('button', { name: /Повторить образ/i })
    expect(repeat).toBeEnabled()
    expect(screen.queryByText('Загрузите референс для этой модели')).not.toBeInTheDocument()
    expect(screen.queryByText('Минимум 1 обязателен')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(screen.queryByDisplayValue(privateRepeat.prompt)).not.toBeInTheDocument()
    fireEvent.click(repeat)

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      model: modelId, sourceFeedGenId: 42, prompt: '', references: [],
    }))
  })

  it('still requires a local reference for a standalone edit generation', () => {
    const onSubmit = jest.fn()
    render(<ImageGeneratorForm models={editModels} onSubmit={onSubmit} isSubmitting={false} credits={100} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My standalone edit' } })

    const launch = screen.getByRole('button', { name: /Запустить фото/i })
    expect(launch).toBeDisabled()
    expect(screen.getByText('Загрузите референс для этой модели')).toBeInTheDocument()
    fireEvent.click(launch)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('preserves the ordered replacement references and source ID', async () => {
    const onSubmit = jest.fn().mockResolvedValue(true)
    const replacements = ['https://example.test/replacement-a.png', 'https://example.test/replacement-b.png']
    render(<ImageGeneratorForm models={editModels} onSubmit={onSubmit} promptPreset={{
      ...privateRepeat,
      initialReferences: replacements.map((url, index) => ({ id: String(index), name: `Replacement ${index + 1}`, type: 'image', url, size: 0 })),
    }} isSubmitting={false} credits={100} />)
    fireEvent.click(screen.getByRole('button', { name: /Повторить образ/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      sourceFeedGenId: 42, prompt: '', references: replacements,
    }))
  })
})
