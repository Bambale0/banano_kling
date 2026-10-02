import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

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

    fireEvent.click(screen.getByRole('button', { name: /Запустить видео/i }))
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

    fireEvent.click(screen.getByRole('button', { name: /Запустить видео/i }))

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
