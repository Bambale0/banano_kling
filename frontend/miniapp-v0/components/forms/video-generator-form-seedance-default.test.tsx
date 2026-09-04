import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

jest.mock('@/components/forms/model-select', () => ({
  ModelSelect: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <div>
      <div data-testid="model">{value}</div>
      <button type="button" onClick={() => onChange('seedance_2')}>select Seedance 2.0</button>
    </div>
  ),
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
jest.mock('@/components/forms/upload-area', () => ({
  UploadArea: () => <div data-testid="upload-area" />,
}))

import { VideoGeneratorForm } from '@/components/forms/video-generator-form'
import type { VideoModel } from '@/lib/types'

const models: VideoModel[] = [
  {
    id: 'v3_pro',
    label: 'Kling 3.0',
    description: 'default',
    durations: [5],
    ratios: ['16:9'],
    supports: ['text', 'imgtxt'],
    costs: { '5': 5 },
    max_image_references: 8,
  },
  {
    id: 'seedance_2',
    label: 'Bytedance Seedance 2.0',
    description: 'image to video',
    durations: [5, 10, 15],
    ratios: ['16:9', '9:16', '1:1'],
    supports: ['text', 'imgtxt', 'video'],
    costs: { '5': 2, '10': 4, '15': 6 },
    max_image_references: 9,
    max_video_references: 3,
  },
]

describe('Seedance 2.0 model defaults', () => {
  it('opens Photo + Text when Seedance 2.0 is selected', async () => {
    render(
      <VideoGeneratorForm
        models={models}
        onSubmit={jest.fn().mockResolvedValue(undefined)}
        isSubmitting={false}
        credits={100}
      />,
    )

    expect(screen.getByTestId('scenario')).toHaveTextContent('text')
    fireEvent.click(screen.getByRole('button', { name: /select Seedance 2\.0/i }))

    await waitFor(() => {
      expect(screen.getByTestId('model')).toHaveTextContent('seedance_2')
      expect(screen.getByTestId('scenario')).toHaveTextContent('imgtxt')
    })
  })
})
