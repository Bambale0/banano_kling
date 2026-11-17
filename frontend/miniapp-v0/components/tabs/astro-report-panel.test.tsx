import '@testing-library/jest-dom'
import { useRef } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AstroReportPanel, buildAstroReportInput } from './astro-report-panel'

jest.mock('../../lib/api', () => ({ getInitData: () => 'synthetic-telegram-signed' }))

function MountedReport({ revision = 0 }: { revision?: number }) {
  const form = useRef<HTMLFormElement>(null)
  return <>
    <form ref={form}>
      <input name="person-date" defaultValue="29.02.2000" />
      <input name="person-time" defaultValue="13:45" />
      <input name="person-place-id" defaultValue="498817" />
      <input name="person-timezone" defaultValue="Etc/Forged" />
    </form>
    <AstroReportPanel service="natal" formRef={form} period="" formRevision={revision} />
  </>
}


function birthForm() {
  const form = new FormData()
  form.set('person-date', '29.02.2000')
  form.set('person-time', '13:45')
  form.set('person-place-id', '498817')
  return form
}

describe('Astro long-report verified input contract', () => {
  it('sends only canonical city IDs and birth time for natal and karma', () => {
    const form = birthForm()
    form.set('person-place', 'some injected place name')
    form.set('person-timezone', 'Etc/Forged')
    expect(buildAstroReportInput('natal', form, '')).toEqual({
      place_id: 498817, date: '29.02.2000', time: '13:45',
    })
    expect(buildAstroReportInput('karma', form, '')).toEqual({
      place_id: 498817, date: '29.02.2000', time: '13:45',
    })
  })

  it('requires distinct confirmed birth cities for compatibility', () => {
    const form = birthForm()
    form.set('partner-date', '02.06.2001')
    form.set('partner-time', '11:30')
    form.set('partner-place-id', '2950159')
    expect(buildAstroReportInput('compatibility', form, '')).toEqual({
      person_a: { place_id: 498817, date: '29.02.2000', time: '13:45' },
      person_b: { place_id: 2950159, date: '02.06.2001', time: '11:30' },
    })
    form.set('partner-place-id', '')
    expect(() => buildAstroReportInput('compatibility', form, '')).toThrow('город')
  })

  it('keeps annual, monthly, solar and lunar periods distinct', () => {
    const form = birthForm()
    expect(buildAstroReportInput('year', form, '2028')).toMatchObject({ period: '2028' })
    expect(buildAstroReportInput('month', form, '2028-02')).toMatchObject({ period: '2028-02' })
    form.set('solar-place-id', '2950159')
    expect(buildAstroReportInput('solar', form, '2028')).toMatchObject({
      place_id: 498817, return_place_id: 2950159, period: '2028',
    })
    form.set('lunar-place-id', '498817')
    expect(buildAstroReportInput('lunar', form, '2028-02')).toEqual({
      period: '2028-02', place_id: 498817,
    })
  })

  it('rejects free-text place, impossible dates and missing lunar city', () => {
    const form = birthForm()
    form.set('person-place-id', 'NaN')
    expect(() => buildAstroReportInput('natal', form, '')).toThrow('город')
    form.set('person-place-id', '498817')
    form.set('person-date', '31.02.2000')
    expect(() => buildAstroReportInput('natal', form, '')).toThrow('дату')
    expect(() => buildAstroReportInput('lunar', form, '2028-02')).toThrow('город')
  })
})

describe('Astro long-report Mini App integration', () => {
  const originalFetch = global.fetch
  afterEach(() => Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch }))

  it('requires opt-in consent, starts a single owner-scoped task and renders full result', async () => {
    const identifier = 'a'.repeat(32)
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: url.endsWith('/start') ? 202 : 200,
      json: async () => url.endsWith('/start')
        ? { ok: true, job_id: identifier }
        : { ok: true, status: 'completed', report: {
          schema_version: 'astro.report.v1', service_id: 'natal', word_count: 10000,
          sections: [{ id: 'intro', title: 'Паспорт натальной карты', text: 'Проверенная символическая интерпретация.' }],
          disclaimer: 'Не является научным прогнозом.',
        } },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    const start = screen.getByRole('button', { name: 'Создать полный ИИ-разбор' })
    expect(start).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(start).not.toBeDisabled()
    fireEvent.click(start)
    const result = await screen.findByLabelText('Готовый полный ИИ-разбор')
    expect(result).toHaveTextContent('Паспорт натальной карты')
    expect(result).toHaveTextContent('Проверенная символическая интерпретация.')
    const posts = mock.mock.calls.filter(([url]) => url.endsWith('/start'))
    expect(posts).toHaveLength(1)
    const body = JSON.parse(posts[0][1].body)
    expect(body).toMatchObject({ init_data: 'synthetic-telegram-signed',
      service_id: 'natal', consent: true, input: { place_id: 498817,
        date: '29.02.2000', time: '13:45' },
    })
    expect(body.input).not.toHaveProperty('timezone')
    expect(body.input).not.toHaveProperty('longitude')
  })

  it('recovers a saved report from history without generating again', async () => {
    const identifier = 'b'.repeat(32)
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: 200, json: async () => url.endsWith('/history')
        ? { ok: true, jobs: [{ job_id: identifier, service_id: 'natal',
          status: 'completed', created_at: 1794931200, attempts: 1 }] }
        : { ok: true, status: 'completed', report: {
          schema_version: 'astro.report.v1', service_id: 'natal', word_count: 10000,
          sections: [{ id: 'return', title: 'Сохранённый разбор', text: 'Содержание из SQL.' }],
          disclaimer: 'Символический текст.',
        } },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('button', { name: 'Мои предыдущие отчёты' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }))
    expect(await screen.findByLabelText('Готовый полный ИИ-разбор')).toHaveTextContent('Содержание из SQL.')
    expect(mock.mock.calls.some(([url]) => url.endsWith('/start'))).toBe(false)
  })

  it('invalidates a previously shown report when birth inputs change', async () => {
    const identifier = 'c'.repeat(32)
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: url.endsWith('/history') ? 200 : 200,
      json: async () => url.endsWith('/history')
        ? { ok: true, jobs: [{ job_id: identifier, service_id: 'natal',
          status: 'completed', created_at: 1794931200, attempts: 1 }] }
        : { ok: true, status: 'completed', report: {
          schema_version: 'astro.report.v1', service_id: 'natal', word_count: 10000,
          sections: [{ id: 'intro', title: 'Исходная карта', text: 'Текст предыдущего отчёта.' }],
          disclaimer: 'Символический текст.',
        } },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    const { rerender } = render(<MountedReport revision={0} />)
    fireEvent.click(screen.getByRole('button', { name: 'Мои предыдущие отчёты' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }))
    expect(await screen.findByLabelText('Готовый полный ИИ-разбор')).toHaveTextContent('Текст предыдущего отчёта.')
    rerender(<MountedReport revision={1} />)
    expect(screen.queryByLabelText('Готовый полный ИИ-разбор')).not.toBeInTheDocument()
    expect(screen.getByText(/Исходные данные изменены/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Создать полный ИИ-разбор' })).toBeDisabled()
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(0)
  })

  it('restarts a terminally failed owned report only after fresh consent', async () => {
    const identifier = 'd'.repeat(32)
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: url.endsWith('/retry') ? 202 : 200,
      json: async () => url.endsWith('/history')
        ? { ok: true, jobs: [{ job_id: identifier, service_id: 'natal',
          status: 'failed', attempts: 4, created_at: 1794931200 }] }
        : url.endsWith('/retry')
          ? { ok: true, job_id: identifier, status: 'queued' }
          : { ok: true, status: 'failed', error_code: 'temporary_provider_failure' },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('button', { name: 'Мои предыдущие отчёты' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Повторить отчёт/ })).toBeInTheDocument())
    const retry = screen.getByRole('button', { name: /Повторить отчёт/ })
    expect(retry).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(retry).not.toBeDisabled()
    fireEvent.click(retry)
    await waitFor(() => expect(mock.mock.calls.filter(([url]) => url.endsWith('/retry'))).toHaveLength(1))
    const body = JSON.parse(mock.mock.calls.find(([url]) => url.endsWith('/retry'))![1].body)
    expect(body).toEqual({ init_data: 'synthetic-telegram-signed', job_id: identifier, consent: true })
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(0)
  })

  it('can retry report creation after a temporary 503 without navigating away', async () => {
    const identifier = 'e'.repeat(32)
    let startCalls = 0
    const mock = jest.fn().mockImplementation((url: string) => {
      if (url.endsWith('/start')) {
        startCalls += 1
        return Promise.resolve(startCalls === 1
          ? { ok: false, status: 503 }
          : { ok: true, status: 202, json: async () => ({ ok: true, job_id: identifier }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({
        ok: true, status: 'completed', report: {
          schema_version: 'astro.report.v1', service_id: 'natal', word_count: 100,
          sections: [{ id: 'intro', title: 'Восстановленный разбор', text: 'Сервер снова доступен.' }],
          disclaimer: 'Тестовая интерпретация.',
        },
      }) })
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Создать полный ИИ-разбор' }))
    await waitFor(() => expect(screen.getByText(/ещё не включены на сервере/)).toBeInTheDocument())
    // A previously unavailable server can be enabled without remounting the Mini App.
    const retry = screen.getByRole('button', { name: 'Создать полный ИИ-разбор' })
    expect(retry).toBeEnabled()
    fireEvent.click(retry)
    expect(await screen.findByLabelText('Готовый полный ИИ-разбор')).toHaveTextContent('Сервер снова доступен.')
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(2)
  })

  it('does not hide report creation when report history temporarily returns 503', async () => {
    const mock = jest.fn().mockResolvedValue({ ok: false, status: 503 })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('button', { name: 'Мои предыдущие отчёты' }))
    await waitFor(() => expect(screen.getByText(/Длинные ИИ-разборы пока не включены/)).toBeInTheDocument())
    // Reading history is optional; a transient error must not lock report creation.
    expect(screen.getByRole('button', { name: 'Создать полный ИИ-разбор' })).toBeInTheDocument()
  })

  it('can explicitly retry a failed report after a temporary 503', async () => {
    const identifier = 'f'.repeat(32)
    let retryCalls = 0
    const mock = jest.fn().mockImplementation((url: string) => {
      if (url.endsWith('/history')) return Promise.resolve({
        ok: true, status: 200, json: async () => ({ ok: true, jobs: [
          { job_id: identifier, service_id: 'natal', status: 'failed',
            attempts: 2, created_at: 1794931200 },
        ] }),
      })
      if (url.endsWith('/retry')) {
        retryCalls += 1
        return Promise.resolve(retryCalls === 1
          ? { ok: false, status: 503 }
          : { ok: true, status: 202, json: async () => ({ ok: true, job_id: identifier }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({
        ok: true, status: 'failed', error_code: 'temporary_provider_failure',
      }) })
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('button', { name: 'Мои предыдущие отчёты' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Открыть' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Открыть' }))
    const retry = await screen.findByRole('button', { name: 'Повторить отчёт' })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(retry)
    await waitFor(() => expect(screen.getByText(/Создание отчётов временно отключено/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Повторить отчёт' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить отчёт' }))
    await waitFor(() => expect(retryCalls).toBe(2))
  })

  it('shows live animated processing while server confirms a running Astro report', async () => {
    const identifier = 'e'.repeat(32)
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: url.endsWith('/start') ? 202 : 200,
      json: async () => url.endsWith('/start')
        ? { ok: true, job_id: identifier, status: 'queued' }
        : { ok: true, job_id: identifier, status: 'running' },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Создать полный ИИ-разбор' }))
    const progress = await screen.findByTestId('astro-live-processing')
    expect(progress).toHaveTextContent('Задание сохранено')
    await waitFor(() => expect(progress).toHaveTextContent('GPT-6'))
    expect(progress.querySelector('[aria-hidden="true"]')).not.toBeNull()
    expect(progress).not.toHaveTextContent('%')  // No invented progress percentage.
    expect(mock.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(1)
  })

  it('keeps paid generation disabled when server has no stable secret configuration', async () => {
    const mock = jest.fn().mockResolvedValue({ ok: false, status: 503 })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    render(<MountedReport />)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Создать полный ИИ-разбор' }))
    await waitFor(() => expect(screen.getByText(/ещё не включены на сервере/)).toBeInTheDocument())
    expect(screen.queryByLabelText('Готовый полный ИИ-разбор')).not.toBeInTheDocument()
  })
})
