import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

jest.mock('@/components/forms/model-select', () => ({
  ModelSelect: ({ value }: { value: string }) => <div data-testid="model">{value}</div>,
}))
jest.mock('@/components/forms/ratio-select', () => ({
  RatioSelect: ({ value }: { value: string }) => <div data-testid="ratio">{value}</div>,
}))
jest.mock('@/components/forms/scenario-select', () => ({
  ScenarioSelect: ({ value }: { value: string }) => <div data-testid="scenario">{value}</div>,
}))
jest.mock('@/components/forms/duration-select', () => ({
  DurationSelect: ({ value }: { value: number }) => <div data-testid="duration">{value}</div>,
}))

import { VideoGeneratorForm } from '@/components/forms/video-generator-form'
import { MiniAppApiError } from '@/lib/api'
import type { UploadedFile, VideoModel, VideoPromptPreset } from '@/lib/types'

const models: VideoModel[] = [{
  id: 'seedance_2_5',
  label: 'Seedance 2.5',
  description: 'video',
  durations: [5, 10],
  ratios: ['16:9'],
  supports: ['text', 'imgtxt', 'video'],
  costs: { '5': 5, '10': 10 },
  max_image_references: 8,
  max_video_references: 5,
}]

const preset: VideoPromptPreset = {
  title: 'Повторить видео',
  prompt: 'animate this frame',
  model: 'seedance_2_5',
  scenario: 'imgtxt',
  ratio: '16:9',
  duration: 5,
  sourceFeedGenId: 42,
  initialStartImage: [],
  initialPhotoReferences: [],
}

const savedFrame: UploadedFile = {
  id: 'saved_1',
  name: 'saved-frame.jpg',
  url: 'https://example.test/saved-frame.jpg',
  type: 'image',
  size: 0,
}

const measuredVideoQuote = {
  quote_hash: 'test-measured-quote', cost: 15, source_video_seconds: 10,
  output_seconds: 5, billable_seconds: 15, admin_free: false,
}

describe('VideoGeneratorForm repeat photo references', () => {
  it('uses a saved photo reference without a separate start-image field', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const firstConsumed = jest.fn()
    const view = render(
      <VideoGeneratorForm
        models={models}
        onSubmit={onSubmit}
        savedImageReferences={[savedFrame]}
        promptPreset={preset}
        onPromptPresetConsumed={firstConsumed}
        isSubmitting={false}
        credits={100}
      />,
    )

    await waitFor(() => expect(firstConsumed).toHaveBeenCalled())
    fireEvent.click(screen.getAllByRole('button', { name: /saved-frame\.jpg/i })[0])

    // savedReferences changes in AppContext cause VideoTab to rerender with a fresh
    // inline onPromptPresetConsumed callback while the same preset can still be present.
    view.rerender(
      <VideoGeneratorForm
        models={models}
        onSubmit={onSubmit}
        savedImageReferences={[savedFrame]}
        promptPreset={preset}
        onPromptPresetConsumed={() => undefined}
        isSubmitting={false}
        credits={100}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0].startImage).toBeNull()
    expect(onSubmit.mock.calls[0][0].references).toEqual([savedFrame.url])
    expect(screen.queryByText('Стартовое изображение')).not.toBeInTheDocument()
  })

  it('lets a source-aware Sedance video repeat adding a photo without requiring a new video ref', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const repeatPreset: VideoPromptPreset = {
      ...preset,
      prompt: '',
      scenario: 'video',
      sourceFeedGenId: 42,
    }

    render(
      <VideoGeneratorForm
        models={models}
        onSubmit={onSubmit}
        savedImageReferences={[savedFrame]}
        promptPreset={repeatPreset}
        onPromptPresetConsumed={() => undefined}
        isSubmitting={false}
        credits={100}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'saved-frame.jpg' }))
    expect(screen.queryByText('Загрузите видео-референс')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      model: 'seedance_2_5',
      scenario: 'video',
      sourceFeedGenId: 42,
      references: [savedFrame.url],
      videoReferences: [],
    }))
  })

})


describe('private video repeat prompt boundary', () => {
  it('requires and submits the configured structured values without exposing bindings', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    render(<VideoGeneratorForm models={models} onSubmit={onSubmit} isSubmitting={false} credits={100} promptPreset={{
      ...preset,
      prompt: 'SYNTHETIC_PRIVATE_RECIPE',
      promptHidden: true,
      repeatUserFields: [{
        key: 'clothes', label: 'Одежда', type: 'text', required: true,
        choices: ['красное платье', 'чёрный костюм'],
      }],
    }} />)
    const launch = screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })
    expect(launch).toBeDisabled()
    expect(screen.queryByDisplayValue('SYNTHETIC_PRIVATE_RECIPE')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'красное платье' }))
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      sourceFeedGenId: 42,
      repeatUserValues: { clothes: 'красное платье' },
    })))
  })

  it('clears contradictory hidden source text, preserves user edits on rerender, and clears on another repeat', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const hidden = { ...preset, prompt: 'SYNTHETIC_PRIVATE_RECIPE', promptHidden: true }
    const props = { models, onSubmit, isSubmitting: false, credits: 100 }
    const view = render(<VideoGeneratorForm {...props} promptPreset={hidden} />)
    const textbox = screen.getByRole('textbox')
    expect(textbox).toHaveValue('')
    expect(screen.queryByDisplayValue('SYNTHETIC_PRIVATE_RECIPE')).not.toBeInTheDocument()
    fireEvent.change(textbox, { target: { value: 'My additional instruction' } })
    view.rerender(<VideoGeneratorForm {...props} promptPreset={hidden} onPromptPresetConsumed={() => undefined} />)
    expect(textbox).toHaveValue('My additional instruction')
    fireEvent.click(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: 'My additional instruction', sourceFeedGenId: 42 })))
    view.rerender(<VideoGeneratorForm {...props} promptPreset={{ ...hidden, sourceFeedGenId: 43 }} />)
    expect(textbox).toHaveValue('')
    view.unmount()
    render(<VideoGeneratorForm {...props} promptPreset={hidden} />)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('preserves an ordinary visible owner prompt', () => {
    render(<VideoGeneratorForm models={models} onSubmit={jest.fn()} isSubmitting={false} credits={100} promptPreset={{ ...preset, promptHidden: false }} />)
    expect(screen.getByRole('textbox')).toHaveValue(preset.prompt)
  })
})


describe('video repeat replacement slots', () => {
  const slots = {
    version: 1, available: true, cost_multiplier: 2, duration_costs: { '5': 10, '10': 20 }, pricing_quality: '720p',
    images: [
      { index: 0, role: 'first_frame', binding: 'upload' },
      { index: 1, role: 'last_frame', binding: 'fixed' },
      { index: 2, role: 'reference', binding: 'upload' },
    ],
    videos: [{ index: 0, role: 'reference', binding: 'fixed' }, { index: 1, role: 'reference', binding: 'upload' }],
  }
  const secondFrame: UploadedFile = { ...savedFrame, id: 'second', name: 'second.jpg', url: 'https://example.test/second.jpg' }
  const savedVideo: UploadedFile = { ...savedFrame, id: 'clip', name: 'clip.mp4', url: 'https://example.test/clip.mp4', type: 'video' }
  const descriptorPreset = { ...preset, prompt: '', promptHidden: true, scenario: 'video', repeatReferenceSlots: slots } as VideoPromptPreset

  it('requires typed replacements and submits them in slot order, never the hidden source refs', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const { container } = render(<VideoGeneratorForm models={models} onSubmit={onSubmit} isSubmitting={false} credits={100}
      onQuote={jest.fn().mockResolvedValue(measuredVideoQuote)}
      promptPreset={{ ...descriptorPreset, initialPhotoReferences: [{ ...savedFrame, url: 'https://example.test/private-source.jpg' }] }}
      savedImageReferences={[savedFrame, secondFrame]} savedVideoReferences={[savedVideo]} />)
    const launch = screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })
    expect(launch).toBeDisabled()
    expect(screen.getByText('Сохранено автором: 2')).toBeInTheDocument()
    expect(container.innerHTML).not.toContain('private-source.jpg')
    fireEvent.click(within(screen.getByRole('group', { name: 'Фото 3' })).getByRole('button', { name: 'second.jpg' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Видео 2' })).getByRole('button', { name: 'clip.mp4' }))
    expect(launch).toBeDisabled()
    fireEvent.click(within(screen.getByRole('group', { name: 'Первый кадр · Фото 1' })).getByRole('button', { name: 'saved-frame.jpg' }))
    expect(launch).toBeEnabled()
    fireEvent.click(launch)
    await screen.findByText(/Видеореференсы: 10 с/)
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      sourceFeedGenId: 42, prompt: '', startImage: null,
      references: [savedFrame.url, secondFrame.url], videoReferences: [savedVideo.url],
    })))
  })
})


describe('video repeat slot lifecycle', () => {
  const fixed: VideoPromptPreset = { ...preset, prompt: '', promptHidden: true, scenario: 'video', repeatReferenceSlots: {
    version: 1, available: true, cost_multiplier: 2, duration_costs: { '5': 10, '10': 20 }, pricing_quality: '720p', images: [{ index: 0, role: 'first_frame', binding: 'fixed' }],
    videos: [{ index: 0, role: 'reference', binding: 'fixed' }],
  } }
  it('can repeat all-fixed inputs without extra uploads and prevents duplicate clicks', async () => {
    let finish!: () => void
    const onSubmit = jest.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    render(<VideoGeneratorForm models={models} onSubmit={onSubmit} onQuote={jest.fn().mockResolvedValue(measuredVideoQuote)} isSubmitting={false} credits={100} promptPreset={fixed} />)
    const launch = screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })
    expect(launch).toBeEnabled()
    fireEvent.click(launch)
    await screen.findByText(/Видеореференсы: 10 с/)
    expect(onSubmit).not.toHaveBeenCalled()
    fireEvent.click(launch)
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ references: [], videoReferences: [] }))
    finish()
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Референсы повтора' })).not.toBeInTheDocument())
  })
  it('blocks unavailable or unknown descriptors and resets for a fresh publication', () => {
    const props = { models, onSubmit: jest.fn(), isSubmitting: false, credits: 100 }
    const view = render(<VideoGeneratorForm {...props} promptPreset={{ ...fixed, repeatReferenceSlots: { ...fixed.repeatReferenceSlots!, available: false } }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Откройте публикацию заново')
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
    view.rerender(<VideoGeneratorForm {...props} promptPreset={fixed} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeEnabled()
    view.rerender(<VideoGeneratorForm {...props} promptPreset={{ ...fixed, repeatReferenceSlots: { ...fixed.repeatReferenceSlots!, version: 2 } as never }} />)
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
  })
  it('blocks a typed repeat when its source model is unavailable', () => {
    render(<VideoGeneratorForm models={models} onSubmit={jest.fn()} isSubmitting={false} credits={100} promptPreset={{ ...fixed, model: 'missing-model' }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Модель исходной публикации сейчас недоступна')
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
  })
  it('blocks a rejected stale recipe until it is reopened and keeps user prompt edits', async () => {
    const props = { models, onSubmit: jest.fn().mockRejectedValue(new MiniAppApiError('Разрешение изменилось', 'repeat_permission_changed')), onQuote: jest.fn().mockResolvedValue(measuredVideoQuote), isSubmitting: false, credits: 100 }
    const view = render(<VideoGeneratorForm {...props} promptPreset={fixed} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My adjustment' } })
    fireEvent.click(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i }))
    await screen.findByText(/Видеореференсы: 10 с/)
    fireEvent.click(screen.getByRole('button', { name: /Подтвердить цену и запустить/i }))
    await screen.findByText('Разрешение изменилось')
    expect(screen.getByRole('textbox')).toHaveValue('My adjustment')
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
    view.rerender(<VideoGeneratorForm {...props} promptPreset={{ ...fixed }} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeEnabled()
  })
  it('ignores an upload finishing after a newer repeat opens', async () => {
    let finish!: (file: UploadedFile) => void
    const upload = jest.fn(() => new Promise<UploadedFile>((resolve) => { finish = resolve }))
    const oneSlot: VideoPromptPreset = { ...fixed, repeatReferenceSlots: {
      version: 1, available: true, cost_multiplier: 2, duration_costs: { '5': 10, '10': 20 }, pricing_quality: '720p', images: [{ index: 0, role: 'reference', binding: 'upload' }], videos: [],
    } }
    const props = { models, onSubmit: jest.fn(), isSubmitting: false, credits: 100, onUploadImageReference: upload }
    const view = render(<VideoGeneratorForm {...props} promptPreset={oneSlot} />)
    const input = view.container.querySelector('input[type="file"]')!
    fireEvent.change(input, { target: { files: [new File(['image'], 'old.jpg', { type: 'image/jpeg' })] } })
    expect(upload).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
    view.rerender(<VideoGeneratorForm {...props} promptPreset={{ ...oneSlot, sourceFeedGenId: 43 }} />)
    finish({ ...savedFrame, name: 'old.jpg' })
    await waitFor(() => expect(screen.queryByText('old.jpg')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })).toBeDisabled()
  })
})


describe('legacy publication repeat slot descriptors', () => {
  it('requires both missing photos before launching a four-slot recipe with a retained tail', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    const secondPhoto: UploadedFile = {
      ...savedFrame, id: 'legacy-second', name: 'second-person.jpg',
      url: 'https://example.test/second-person.jpg',
    }
    const privateSource = 'https://example.test/private-retained-reference.jpg'
    const legacyPreset: VideoPromptPreset = {
      ...preset, prompt: '', promptHidden: true,
      initialPhotoReferences: [{ ...savedFrame, url: privateSource }],
      repeatReferenceSlots: {
        version: 1, available: true, cost_multiplier: 1,
        duration_costs: { '5': 5, '10': 10 }, pricing_quality: '720p',
        images: [
          { index: 0, role: 'reference', binding: 'upload' },
          { index: 1, role: 'reference', binding: 'upload' },
          { index: 2, role: 'reference', binding: 'fixed' },
          { index: 3, role: 'reference', binding: 'fixed' },
        ],
        videos: [],
      },
    }
    const { container } = render(
      <VideoGeneratorForm models={models} onSubmit={onSubmit} isSubmitting={false} credits={100}
        promptPreset={legacyPreset} savedImageReferences={[savedFrame, secondPhoto]} />,
    )
    const launch = screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость|Подтвердить цену и запустить/i })
    expect(launch).toBeDisabled()
    expect(screen.getByText('Сохранено автором: 2')).toBeInTheDocument()
    expect(screen.getByText('Фото 3 · Сохранён автором')).toBeInTheDocument()
    expect(screen.getByText('Фото 4 · Сохранён автором')).toBeInTheDocument()
    expect(container.innerHTML).not.toContain(privateSource)

    // Fill Image2 first: payload order must follow slots, not interaction order.
    fireEvent.click(within(screen.getByRole('group', { name: 'Фото 2' }))
      .getByRole('button', { name: secondPhoto.name }))
    expect(launch).toBeDisabled()
    fireEvent.click(launch)
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.click(within(screen.getByRole('group', { name: 'Фото 1' }))
      .getByRole('button', { name: savedFrame.name }))
    expect(launch).toBeEnabled()
    fireEvent.click(launch)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const submitted = onSubmit.mock.calls[0][0]
    expect(submitted).toEqual(expect.objectContaining({
      sourceFeedGenId: 42, prompt: '', startImage: null,
      references: [savedFrame.url, secondPhoto.url], videoReferences: [],
    }))
    expect(JSON.stringify(submitted)).not.toContain(privateSource)
  })
})


describe('retriable errors never masquerade as revoked author consent', () => {
  const safePreset: VideoPromptPreset = { ...preset, prompt: '', promptHidden: true, scenario: 'imgtxt',
    repeatReferenceSlots: { version: 1, available: true, cost_multiplier: 1,
      duration_costs: { '5': 5, '10': 10 }, pricing_quality: '720p',
      images: [{ index: 0, role: 'first_frame', binding: 'fixed' }], videos: [] } }

  it('provider 503 preserves the authorized repeat and permits a second submission', async () => {
    const onSubmit = jest.fn()
      .mockRejectedValueOnce(new MiniAppApiError('Провайдер временно недоступен', 'provider_unavailable'))
      .mockResolvedValueOnce(undefined)
    render(<VideoGeneratorForm models={models} onSubmit={onSubmit}
      promptPreset={safePreset} credits={100} isSubmitting={false} />)
    const button = screen.getByRole('button', { name: /Запустить видео|Рассчитать точную стоимость/ })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    await screen.findByText('Провайдер временно недоступен')
    expect(screen.queryByText(/Повтор недоступен\. Откройте публикацию/)).not.toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Референсы повтора' })).toHaveTextContent('Сохранено автором: 1')
    expect(button).toBeEnabled()
    fireEvent.click(button)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2))
  })

  it('server-side repeat permission change locks retry and preserves user edits until re-open', async () => {
    const onSubmit = jest.fn().mockRejectedValue(new MiniAppApiError(
      'Разрешение или исходные файлы изменились', 'repeat_permission_changed'))
    render(<VideoGeneratorForm models={models} onSubmit={onSubmit}
      promptPreset={safePreset} credits={100} isSubmitting={false} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My edits' } })
    fireEvent.click(screen.getByRole('button', { name: /Запустить видео/ }))
    await screen.findByText('Разрешение или исходные файлы изменились')
    expect(screen.getByText(/Повтор недоступен/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
    expect(screen.getByRole('textbox')).toHaveValue('My edits')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('a missing model is not falsely labeled author permission revoked', () => {
    render(<VideoGeneratorForm models={models} onSubmit={jest.fn()}
      promptPreset={{ ...safePreset, model: 'offline-model' }} credits={100} isSubmitting={false} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Модель исходной публикации сейчас недоступна')
    expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  })
})
