import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { VideoGeneratorForm } from '@/components/forms/video-generator-form'
import type { VideoModel, VideoPromptPreset } from '@/lib/types'

jest.mock('@/components/forms/model-select', () => ({ ModelSelect: () => <div data-testid="model-select" /> }))
jest.mock('@/components/forms/ratio-select', () => ({ RatioSelect: () => <div data-testid="ratio-select" /> }))
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: () => <div data-testid="scenario-select" /> }))
jest.mock('@/components/forms/duration-select', () => ({ DurationSelect: () => <div data-testid="duration-select" /> }))
jest.mock('@/components/forms/upload-area', () => ({
  UploadArea: ({ required }: { required?: boolean }) => (
    <div data-testid="upload-area" data-required={required ? 'true' : 'false'} />
  ),
}))

const models = [
  {
    id: 'seedance_2',
    label: 'Seedance 2.0',
    description: 'Seedance',
    durations: [5],
    ratios: ['16:9'],
    supports: ['text', 'imgtxt', 'video'],
    costs: { '5': 4 },
    max_image_references: 9,
    max_video_references: 3,
  },
] as VideoModel[]

const repeatPreset = {
  title: 'Повторить видео',
  prompt: '',
  model: 'seedance_2',
  scenario: 'imgtxt',
  ratio: '16:9',
  duration: 5,
  sourceFeedGenId: 42,
  promptHidden: true,
} as VideoPromptPreset

describe('VideoGeneratorForm server-side repeat media', () => {
  it('does not require a new Seedance start image when source generation will restore it', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)

    render(
      <VideoGeneratorForm
        models={models}
        onSubmit={onSubmit}
        promptPreset={repeatPreset}
        onPromptPresetConsumed={jest.fn()}
        isSubmitting={false}
        credits={100}
      />,
    )

    const launchButton = await screen.findByRole('button', { name: /Запустить видео/i })
    await waitFor(() => expect(launchButton).toBeEnabled())
    expect(screen.getByText('(из исходной генерации)')).toBeInTheDocument()

    fireEvent.click(launchButton)

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        model: 'seedance_2',
        scenario: 'imgtxt',
        sourceFeedGenId: 42,
        startImage: null,
      }),
    )
  })
})
