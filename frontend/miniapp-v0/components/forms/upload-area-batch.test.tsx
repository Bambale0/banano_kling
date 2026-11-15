import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { UploadArea } from './upload-area'
import type { UploadedFile } from '@/lib/types'
import { sendMiniAppClientLog } from '@/lib/api'

jest.mock('@/lib/api', () => ({ sendMiniAppClientLog: jest.fn() }))

it('keeps the picker closed until all original selected files finish uploading', async () => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const received: string[] = []
  function Form() {
    const [files, setFiles] = useState<UploadedFile[]>([])
    return <UploadArea files={files} onFilesChange={setFiles} accept="image/*" maxFiles={5}
      onUpload={async file => {
        received.push(file.name)
        if (file.name === 'first.png') await pending
        return { id: file.name, name: file.name, url: 'https://example.test/' + file.name, type: 'image', size: file.size }
      }} />
  }
  const { container } = render(<Form />)
  const input = container.querySelector('input[type=file]') as HTMLInputElement
  const user = userEvent.setup()
  await user.upload(input, [new File(['first'], 'first.png', { type: 'image/png' }),
    new File(['second'], 'second.png', { type: 'image/png' })])
  expect(received).toEqual(['first.png'])
  expect(input).toBeDisabled()
  await user.upload(input, new File(['replacement'], 'replacement.png', { type: 'image/png' }))
  expect(received).toEqual(['first.png'])
  await act(async () => { release(); await pending })
  await waitFor(() => expect(received).toEqual(['first.png', 'second.png']))
  await screen.findByText('second.png')
  expect(input).toBeEnabled()
})


it('records per-slot upload success and failure without logging media URLs', async () => {
  ;(sendMiniAppClientLog as jest.Mock).mockClear()
  function Form() {
    const [slots, setSlots] = useState<Record<string, UploadedFile[]>>({})
    return <>{['image-0', 'image-1'].map(key =>
      <div role="group" aria-label={key} key={key}>
        <UploadArea files={slots[key] || []} onFilesChange={next => setSlots(prev => ({ ...prev, [key]: next }))}
          accept="image/*" maxFiles={1} diagnosticContext={`repeat-video:${key}`}
          onUpload={async file => {
            if (key === 'image-1') throw new Error('NetworkError')
            return { id: file.name, name: file.name, url: 'https://example.test/first.png', type: 'image', size: file.size }
          }} />
      </div>)}</>
  }
  render(<Form />)
  for (const key of ['image-0', 'image-1']) {
    const input = within(screen.getByRole('group', { name: key })).getByText(/Нажмите или перетащите/).parentElement!.querySelector('input[type=file]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['photo'], 'photo.png', { type: 'image/png' })] } })
  }
  await waitFor(() => expect(sendMiniAppClientLog).toHaveBeenCalledWith('upload-file-complete',
    expect.objectContaining({ diagnostic_context: 'repeat-video:image-0' })))
  await waitFor(() => expect(sendMiniAppClientLog).toHaveBeenCalledWith('upload-file-failed',
    expect.objectContaining({ diagnostic_context: 'repeat-video:image-1' })))
  expect(JSON.stringify((sendMiniAppClientLog as jest.Mock).mock.calls)).not.toContain('example.test/first.png')
})
