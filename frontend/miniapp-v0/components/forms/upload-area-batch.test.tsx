import '@testing-library/jest-dom'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { UploadArea } from './upload-area'
import type { UploadedFile } from '@/lib/types'

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
