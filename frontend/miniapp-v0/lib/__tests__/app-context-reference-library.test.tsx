import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AppProvider, useApp } from '../app-context'
import { uploadWan3PrimeReference } from '../wan3-prime-api'
import type { UploadedFile } from '../types'

jest.mock('../api', () => ({
  getApiBasePath: () => '/mini-app/api', getInitData: () => 'query_id=synthetic', getStartParamFallback: () => '',
  hasTelegramInitData: () => true, waitForTelegramInitData: async () => true,
  bootstrapApp: async () => ({ ok: true, credits: 100, is_admin: false, telegram_id: 424242,
    image_models: [], video_models: [], recent_tasks: [], payment_packages: [],
    saved_references: [{ id: '7', kind: 'image', filename: 'saved.jpg', url: '/uploads/saved.jpg' }],
  }),
}))

function Library({ file }: { file: UploadedFile }) {
  const { state, addSavedReference } = useApp()
  return <><button onClick={() => addSavedReference(file)}>Добавить WAN</button><ul>
    {state.savedReferences.map(item => <li key={item.id} data-testid={item.id}>{item.url}</li>)}
  </ul></>
}

test('actual Wan uploader and application library keep equal numeric IDs distinct', async () => {
  sessionStorage.clear()
  const originalFetch = global.fetch
  global.fetch = jest.fn(async (url: string | URL | Request, options?: RequestInit) => ({ ok: true, status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(String(url).endsWith('/init')
      ? { ok: true, upload_id: JSON.parse(String(options?.body)).upload_id, chunk_size: 10 }
      : String(url).endsWith('/complete')
        ? { ok: true, url: '/uploads/wan.jpg', filename: 'wan.jpg', kind: 'image', size: 1, reference: { id: 7 } }
        : { ok: true }),
  })) as unknown as typeof fetch
  try {
    const uploaded = await uploadWan3PrimeReference('image', new File(['x'], 'wan.jpg', { type: 'image/jpeg' }))
    const mounted = render(<AppProvider><Library file={uploaded} /></AppProvider>)
    await screen.findByTestId('saved_7')
    fireEvent.click(screen.getByRole('button', { name: 'Добавить WAN' }))
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(screen.getByTestId('saved_7')).toHaveTextContent('/uploads/saved.jpg')
    expect(screen.getByTestId('wan3_7')).toHaveTextContent('/uploads/wan.jpg')
    mounted.unmount()
  } finally { global.fetch = originalFetch }
})
