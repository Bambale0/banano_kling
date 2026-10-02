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
    const onSubmit = jest.fn().mockResolvedValue(undefined)
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
