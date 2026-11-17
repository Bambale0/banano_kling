import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { AstroTab, ASTRO_SERVICES } from './astro-tab'

describe('Astro concept screens', () => {
  it('shows all seven functions and keeps them selectable', () => {
    render(<AstroTab />)
    for (const service of ASTRO_SERVICES) {
      expect(screen.getByText(service.title)).toBeInTheDocument()
    }
    fireEvent.click(screen.getByText('Натальная карта'))
    expect(screen.getByRole('heading', { name: 'Натальная карта' })).toBeInTheDocument()
    expect(screen.getByLabelText('person: дата рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('person: время рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('person: место рождения')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Все разделы/ }))
    expect(screen.getByText('Лунный календарь')).toBeInTheDocument()
  })

  it('adds date separators automatically while typing and normalizes pasted dates', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Натальная карта'))
    const birthDate = screen.getByLabelText('person: дата рождения')
    for (const [typed, expected] of [
      ['1', '1'],
      ['12', '12'],
      ['120', '12.0'],
      ['1203', '12.03'],
      ['12032', '12.03.2'],
      ['12032000', '12.03.2000'],
      ['12/03/2000', '12.03.2000'],
      ['12-03-2000', '12.03.2000'],
      ['1203200000', '12.03.2000'],
      ['12.03.200', '12.03.200'],
      ['12.03', '12.03'],
      ['12', '12'],
      ['', ''],
    ] as const) {
      fireEvent.change(birthDate, { target: { value: typed } })
      expect(birthDate).toHaveValue(expected)
    }
    expect(screen.queryByText('Астрологические интерпретации носят развлекательный характер.'))
      .not.toBeInTheDocument()
  })

  it('masks both birth dates independently on compatibility', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Совместимость'))
    const first = screen.getByLabelText('person: дата рождения')
    const second = screen.getByLabelText('partner: дата рождения')
    fireEvent.change(first, { target: { value: '01021999' } })
    fireEvent.change(second, { target: { value: '29022000' } })
    expect(first).toHaveValue('01.02.1999')
    expect(second).toHaveValue('29.02.2000')
  })

  it('validates birth date instead of submitting fictional astro results', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Натальная карта'))
    fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
    expect(screen.getByRole('status')).toHaveTextContent('корректную дату рождения')

    fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '31.02.2000' } })
    fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Москва, Россия' } })
    fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
    expect(screen.getByRole('status')).toHaveTextContent('корректную дату рождения')

    fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
    fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
    expect(screen.getByRole('status')).toHaveTextContent('Выберите место рождения из предложенного списка')
  })

  it('uses the verified city ID and renders real Placidus houses, ASC/MC and planets', async () => {
    const places = [{
      place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
      timezone: 'Europe/Moscow', latitude: 59.93863, longitude: 30.31413,
      display_name: 'Saint Petersburg, RU', source: 'GeoNames',
    }]
    const result = {
      schema_version: 'astro.natal-facts.v1',
      chart: {
        utc: '2000-02-29T10:45:00+00:00', tz: 'Europe/Moscow',
        house_system: 'Placidus',
        angles: { asc: 118.27, mc: 349.25 },
        cusps: [118.27, 130.03, 145.67, 169.25, 208.70, 262.69,
          298.27, 310.03, 325.67, 349.25, 28.70, 82.69],
        houses: [{ house: 1, cusp_lon: 118.27, sign: 'Cancer', ruler: 'Moon' }],
        body_houses: { Sun: 12, Mercury: 12 },
        ruler_scheme: 'traditional',
        bodies: {
          Sun: { lon: 340.15, speed: 1, retro: false, sign: 'Pisces', deg_in_sign: 10.15 },
          Mercury: { lon: 342.15, speed: -1, retro: true, sign: 'Pisces', deg_in_sign: 12.15 },
        },
        aspects: [{ a: 'Sun', b: 'Mercury', aspect: 'conjunction', orb: -2.0 }],
      },
      accuracy: { birth_time_known: true, moon_position_known: true, houses_available: true },
      disclaimer: 'Symbolic tradition',
    }
    const fetchMock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: 200,
      json: async () => url.endsWith('/places')
        ? { ok: true, results: places } : { ok: true, result },
    }))
    const originalFetch = global.fetch
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
      fireEvent.change(screen.getByLabelText('person: время рождения'), { target: { value: '13:45' } })
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Россия, Санкт-Петербург' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('Europe/Moscow')
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveAttribute('readOnly')
      fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Дома Плацидуса' })).toBeInTheDocument())
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('ASC')
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('MC')
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('Дом 12')
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('управитель Луна')
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('в доме 12')
      expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toHaveTextContent('Рыбы 10.15°')
      const natalRequests = fetchMock.mock.calls.filter(([url]) => url.endsWith('/natal/full'))
      expect(natalRequests).toHaveLength(1)
      const [endpoint, init] = natalRequests[0]
      expect(endpoint).toBe('/mini-app/api/astro/natal/full')
      const payload = JSON.parse(init.body)
      expect(payload).toMatchObject({
        place_id: 498817, date: '29.02.2000', time: '13:45',
      })
      expect(payload).not.toHaveProperty('timezone')
      expect(payload).not.toHaveProperty('latitude')
      expect(payload).not.toHaveProperty('longitude')
      expect(payload).not.toHaveProperty('is_admin')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('does not reveal a natal chart if admin rights are revoked', async () => {
    const originalFetch = global.fetch
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve(
      url.endsWith('/places')
        ? {
          ok: true, status: 200, json: async () => ({ ok: true, results: [{
            place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
            timezone: 'Europe/Moscow', latitude: 59.94, longitude: 30.31,
          }] }),
        }
        : { ok: false, status: 403 },
    ))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Санкт-Петербург' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
      await waitFor(() => expect(screen.getByText(/Нет доступа к расчёту/)).toBeInTheDocument())
      expect(screen.queryByLabelText('Полная рассчитанная натальная карта')).not.toBeInTheDocument()
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('invalidates a previously calculated natal chart after changing birth inputs', async () => {
    const originalFetch = global.fetch
    const fetchMock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: 200,
      json: async () => url.endsWith('/places')
        ? { ok: true, results: [{
          place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
          timezone: 'Europe/Moscow', latitude: 59.94, longitude: 30.31,
        }] }
        : { ok: true, result: {
          schema_version: 'astro.natal-facts.v1',
          chart: {
            utc: '2000-02-29T10:45:00+00:00', tz: 'Europe/Moscow',
            house_system: 'Placidus', angles: { asc: 118, mc: 349 },
            cusps: Array.from({ length: 12 }, (_, i) => i * 30),
            bodies: { Sun: { lon: 340.15, speed: 1, retro: false, sign: 'Pisces', deg_in_sign: 10.15 } },
            aspects: [],
          },
          accuracy: { birth_time_known: true, moon_position_known: true, houses_available: true },
          disclaimer: 'symbolic',
        } },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Санкт-Петербург' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
      await waitFor(() => expect(screen.getByLabelText('Полная рассчитанная натальная карта')).toBeInTheDocument())
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '01.03.2000' } })
      expect(screen.queryByLabelText('Полная рассчитанная натальная карта')).not.toBeInTheDocument()
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('Europe/Moscow')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('ignores a stale natal response after the birth date is edited mid-request', async () => {
    const originalFetch = global.fetch
    let deliver!: (response: unknown) => void
    const unresolved = new Promise((resolve) => { deliver = resolve })
    const fetchMock = jest.fn().mockImplementation((url: string) => {
      if (url.endsWith('/places')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, results: [{
          place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
          timezone: 'Europe/Moscow', latitude: 59.94, longitude: 30.31,
        }] }) })
      }
      return unresolved
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      const date = screen.getByLabelText('person: дата рождения')
      fireEvent.change(date, { target: { value: '29.02.2000' } })
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Санкт-Петербург' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      fireEvent.click(screen.getByRole('button', { name: /Построить натальную карту/ }))
      await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/natal/full'))).toBe(true))
      fireEvent.change(date, { target: { value: '01.03.2000' } })
      await act(async () => {
        deliver({ ok: true, status: 200, json: async () => ({ ok: true, result: {
          schema_version: 'astro.natal-facts.v1',
          chart: {
            utc: '2000-02-29T10:45:00+00:00', tz: 'Europe/Moscow', house_system: 'Placidus',
            angles: { asc: 118.27, mc: 349.25 },
            cusps: Array.from({ length: 12 }, (_, i) => i * 30),
            bodies: { Sun: { lon: 340.15, speed: 1, retro: false, sign: 'Pisces', deg_in_sign: 10.15 } },
            aspects: [],
          },
          accuracy: { birth_time_known: true, moon_position_known: true, houses_available: true },
        } }) })
        await unresolved
      })
      expect(screen.queryByLabelText('Полная рассчитанная натальная карта')).not.toBeInTheDocument()
      expect(date).toHaveValue('01.03.2000')
      expect(screen.getByRole('button', { name: /Построить натальную карту/ })).toBeEnabled()
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('collects two distinct birth profiles for compatibility', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Совместимость'))
    expect(screen.getByText('Первый человек')).toBeInTheDocument()
    expect(screen.getByText('Второй человек')).toBeInTheDocument()
    expect(screen.getByLabelText('person: дата рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('partner: дата рождения')).toBeInTheDocument()
  })

  it('uses two verified GeoNames IDs for exact JPL compatibility', async () => {
    const old = global.fetch
    const mock = jest.fn().mockImplementation((url: string, init: { body: string }) => {
      const input = JSON.parse(init.body)
      const city = String(input.query || '').includes('Таллин')
        ? { place_id: 588409, name: 'Tallinn', country_code: 'EE', timezone: 'Europe/Tallinn' }
        : { place_id: 524901, name: 'Москва', country_code: 'RU', timezone: 'Europe/Moscow' }
      return Promise.resolve({ ok: true, status: 200, json: async () => url.endsWith('/places')
        ? { ok: true, results: [{ ...city, latitude: 55, longitude: 37 }] }
        : { ok: true, result: { schema_version: 'astro.synastry-facts.v1',
          first_accuracy: { birth_time_known: true }, second_accuracy: { birth_time_known: false },
          aspects: [{ a: 'Sun', b: 'Moon', aspect: 'trine', orb: 1.1 }],
          house_overlays: { first_in_second: null, second_in_first: { Sun: 3 } },
        } } })
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Совместимость'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '20.03.2024' } })
      fireEvent.change(screen.getByLabelText('partner: дата рождения'), { target: { value: '01.02.1995' } })
      for (const [prefix, query, name] of [
        ['person', 'Москва', 'Выбрать Москва, Россия'],
        ['partner', 'Таллин', 'Выбрать Tallinn, Эстония'],
      ]) {
        fireEvent.change(screen.getByLabelText(prefix + ': место рождения'), { target: { value: query } })
        await waitFor(() => expect(screen.getByRole('option', { name })).toBeInTheDocument())
        fireEvent.click(screen.getByRole('option', { name }))
      }
      expect(screen.getByLabelText('person: часовой пояс')).toHaveValue('Europe/Moscow')
      expect(screen.getByLabelText('partner: часовой пояс')).toHaveAttribute('readOnly')
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      const result = await screen.findByLabelText('Рассчитанные межкартные аспекты')
      expect(result).toHaveTextContent('Солнце — дом 3')
      expect(result).toHaveTextContent('Дома не определены')
      const post = mock.mock.calls.find(([url]) => url.endsWith('/compatibility/full'))
      expect(JSON.parse(post[1].body)).toMatchObject({
        person_a: { date: '20.03.2024', place_id: 524901 },
        person_b: { date: '01.02.1995', place_id: 588409 },
      })
      expect(JSON.parse(post[1].body).person_a).not.toHaveProperty('timezone')
      expect(JSON.parse(post[1].body).person_b).not.toHaveProperty('latitude')
    } finally { Object.defineProperty(global, 'fetch', { configurable: true, value: old }) }
  })

  it('does not reveal two-person house data after admin role revocation', async () => {
    const originalFetch = global.fetch
    const mock = jest.fn().mockImplementation((url: string, init: { body: string }) => {
      const query = String(JSON.parse(init.body).query || '')
      return Promise.resolve(url.endsWith('/places')
        ? { ok: true, status: 200, json: async () => ({ ok: true, results: [{
          place_id: query.includes('Таллин') ? 588409 : 524901,
          name: query.includes('Таллин') ? 'Tallinn' : 'Москва',
          country_code: query.includes('Таллин') ? 'EE' : 'RU',
          timezone: query.includes('Таллин') ? 'Europe/Tallinn' : 'Europe/Moscow',
          latitude: 55, longitude: 37,
        }] }) }
        : { ok: false, status: 403 })
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Совместимость'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '20.03.2024' } })
      fireEvent.change(screen.getByLabelText('partner: дата рождения'), { target: { value: '01.02.1995' } })
      for (const [prefix, query, name] of [
        ['person', 'Москва', 'Выбрать Москва, Россия'],
        ['partner', 'Таллин', 'Выбрать Tallinn, Эстония'],
      ]) {
        fireEvent.change(screen.getByLabelText(prefix + ': место рождения'), { target: { value: query } })
        await waitFor(() => expect(screen.getByRole('option', { name })).toBeInTheDocument())
        fireEvent.click(screen.getByRole('option', { name }))
      }
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      await waitFor(() => expect(screen.getByText('Нет доступа к расчёту. Повторно откройте приложение Telegram.')).toBeInTheDocument())
      expect(screen.queryByLabelText('Рассчитанные межкартные аспекты')).not.toBeInTheDocument()
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('has a separate month picker for the lunar calendar', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Лунный календарь'))
    expect(screen.getByLabelText('Месяц календаря')).toHaveAttribute('type', 'month')
    expect(screen.queryByText('Дата рождения')).not.toBeInTheDocument()
  })
  it('uses the real admin lunar endpoint and displays computed facts', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        result: {
          period: '2024-03',
          timezone: 'Europe/Moscow',
          days: [{
            date: '2024-03-25', moon_sign: 'Весы', phase: 'убывающая',
            illumination_percent: 100, synodic_day: 15, events: ['Полнолуние'],
          }],
          events: [{ kind: 'Полнолуние', at_local: '2024-03-25T10:00:00+03:00' }],
          ingresses: [{ from_sign: 'Рыбы', to_sign: 'Овен', at_local: '2024-03-12T03:15:00+03:00' }],
        },
      }),
    })
    const originalFetch = global.fetch
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Лунный календарь'))
      fireEvent.change(screen.getByLabelText('Месяц календаря'), { target: { value: '2024-03' } })
      fireEvent.change(screen.getByLabelText('Часовой пояс'), { target: { value: 'Europe/Moscow' } })
      fireEvent.click(screen.getByRole('button', { name: /Открыть лунный календарь/ }))
      await waitFor(() => expect(screen.getByText(/Лунный календарь за 2024-03/)).toBeInTheDocument())
      expect(screen.getByText('2024-03-25')).toBeInTheDocument()
      expect(screen.getByText(/Рыбы → Овен/)).toBeInTheDocument()
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const payload = JSON.parse(fetchMock.mock.calls[0][1].body)
      expect(payload).toMatchObject({ period: '2024-03', timezone: 'Europe/Moscow' })
      expect(payload).not.toHaveProperty('person-date')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('does not display a report after server access is denied', async () => {
    const originalFetch = global.fetch
    Object.defineProperty(global, 'fetch', {
      configurable: true, value: jest.fn().mockResolvedValue({ ok: false, status: 403 }),
    })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Лунный календарь'))
      fireEvent.change(screen.getByLabelText('Месяц календаря'), { target: { value: '2024-03' } })
      fireEvent.click(screen.getByRole('button', { name: /Открыть лунный календарь/ }))
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Нет доступа'))
      expect(screen.queryByLabelText('Рассчитанный лунный календарь')).not.toBeInTheDocument()
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('requests the solar-return location separately from birthplace', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Соляр'))
    expect(screen.getByLabelText('person: место рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('solar: место рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('Период прогноза')).toHaveAttribute('type', 'number')
  })


  it('searches a real GeoNames city and fills natal timezone only after explicit selection', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        ok: true, attribution: '© GeoNames (CC BY 4.0)',
        results: [
          { place_id: 524901, name: 'Москва', country_code: 'RU',
            timezone: 'Europe/Moscow', latitude: 55.75, longitude: 37.62,
            display_name: 'Москва, RU', source: 'GeoNames' },
          { place_id: 6167865, name: 'Moscow', country_code: 'US',
            timezone: 'America/Los_Angeles', latitude: 46.73, longitude: -117,
            display_name: 'Moscow, US', source: 'GeoNames' },
        ],
      }),
    })
    const original = global.fetch
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Москва' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Москва, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Москва, Россия' }))
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('Europe/Moscow')
      expect(screen.getByLabelText('person: место рождения')).toHaveValue('Москва, Россия')
      const placeId = document.querySelector('input[name="person-place-id"]') as HTMLInputElement
      expect(placeId.value).toBe('524901')
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('/mini-app/api/astro/places')
      expect(JSON.parse(init.body)).toMatchObject({ query: 'Москва' })
      expect(init.method).toBe('POST')
      expect(screen.getByLabelText('person: место рождения')).toHaveAttribute('role', 'combobox')

      // Editing a selected place invalidates its canonical id and derived timezone.
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Другой' } })
      expect(placeId.value).toBe('')
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: original })
    }
  })

  it('denied GeoNames search shows safe error without fake locations', async () => {
    const original = global.fetch
    Object.defineProperty(global, 'fetch', {
      configurable: true, value: jest.fn().mockResolvedValue({ ok: false, status: 403 }),
    })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Совместимость'))
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Москва' } })
      await waitFor(() => expect(screen.getByText(/Нет доступа к справочнику городов/)).toBeInTheDocument())
      expect(screen.queryByRole('option', { name: /Выбрать Москва/ })).not.toBeInTheDocument()
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: original })
    }
  })


  it('debounces city lookup and auto-fills the historical zone after explicit country selection', async () => {
    const originalFetch = global.fetch
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({
        ok: true, results: [{
          place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
          timezone: 'Europe/Moscow', latitude: 59.93863, longitude: 30.31413,
          display_name: 'Saint Petersburg, RU', source: 'GeoNames',
        }],
      }),
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: fetchMock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Натальная карта'))
      const city = screen.getByLabelText('person: место рождения')
      fireEvent.change(city, { target: { value: 'Са' } })
      fireEvent.change(city, { target: { value: 'Сан' } })
      fireEvent.change(city, { target: { value: 'Россия, Санкт-Петербург' } })
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
      expect(JSON.parse(fetchMock.mock.calls[0][1].body).query)
        .toBe('Россия, Санкт-Петербург')
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('')
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      expect(screen.getByLabelText('Часовой пояс рождения')).toHaveValue('Europe/Moscow')
      expect(city).toHaveValue('Saint Petersburg, Россия')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: originalFetch })
    }
  })

  it('calculates karma only after choosing a verified city', async () => {
    const original = global.fetch
    const mock = jest.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: 200, json: async () => url.endsWith('/places') ? {
        ok: true, results: [{
          place_id: 498817, name: 'Saint Petersburg', country_code: 'RU',
          timezone: 'Europe/Moscow', latitude: 59.94, longitude: 30.31,
        }],
      } : {
        ok: true, result: {
          schema_version: 'astro.karma-indicators.v1',
          indicators: { TrueNode: { lon: 205.5 } },
          aspects: [{ a: 'Saturn', b: 'TrueNode', aspect: 'square', orb: 2.3 }],
        },
      },
    }))
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Кармический разбор'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      expect(screen.getByRole('status')).toHaveTextContent('Укажите место рождения')
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Санкт' } })
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      expect(screen.getByRole('status')).toHaveTextContent('Выберите город рождения')
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      await waitFor(() => expect(screen.getByLabelText('Рассчитанные кармические показатели')).toBeInTheDocument())
      expect(screen.getByLabelText('Рассчитанные кармические показатели')).toHaveTextContent('Северный лунный узел')
      const post = mock.mock.calls.find(([url]) => url.endsWith('/karma'))
      expect(JSON.parse(post[1].body)).toMatchObject({ place_id: 498817, date: '29.02.2000' })
      expect(JSON.parse(post[1].body)).not.toHaveProperty('latitude')
    } finally {
      Object.defineProperty(global, 'fetch', { configurable: true, value: original })
    }
  })

  it('requires independent verified return city for relocated solar', async () => {
    const old = global.fetch
    const mock = jest.fn().mockImplementation((url: string, init: { body: string }) => {
      const body = JSON.parse(init.body)
      return Promise.resolve({ ok: true, json: async () => url.endsWith('/places')
        ? { ok: true, results: [{ place_id: body.query.includes('Берлин') ? 2950159 : 498817,
          name: body.query.includes('Берлин') ? 'Berlin' : 'Saint Petersburg',
          country_code: body.query.includes('Берлин') ? 'DE' : 'RU',
          timezone: 'Europe/Moscow', latitude: 59.9, longitude: 30.3 }] }
        : { ok: true, result: { schema_version: 'astro.solar-facts.v1',
          solar_return_at_local: '2028-02-29T05:12:00+01:00',
          return_location: { timezone: 'Europe/Berlin' },
          solar_chart: { angles: { asc: 110, mc: 300 },
            cusps: Array.from({ length: 12 }, (_, i) => i * 30), bodies: { Sun: { lon: 340 } } },
        } } })
    })
    Object.defineProperty(global, 'fetch', { configurable: true, value: mock })
    try {
      render(<AstroTab />)
      fireEvent.click(screen.getByText('Соляр'))
      fireEvent.change(screen.getByLabelText('person: дата рождения'), { target: { value: '29.02.2000' } })
      fireEvent.change(screen.getByLabelText('Период прогноза'), { target: { value: '2028' } })
      fireEvent.change(screen.getByLabelText('person: место рождения'), { target: { value: 'Санкт' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Saint Petersburg, Россия' }))
      fireEvent.change(screen.getByLabelText('solar: место рождения'), { target: { value: 'Берлин' } })
      await waitFor(() => expect(screen.getByRole('option', { name: 'Выбрать Berlin, Германия' })).toBeInTheDocument())
      fireEvent.click(screen.getByRole('option', { name: 'Выбрать Berlin, Германия' }))
      fireEvent.click(screen.getByRole('button', { name: 'Получить разбор' }))
      await waitFor(() => expect(screen.getByLabelText('Рассчитанная карта соляра')).toBeInTheDocument())
      expect(JSON.parse(mock.mock.calls.find(([url]) => url.endsWith('/solar'))[1].body))
        .toMatchObject({ place_id: 498817, return_place_id: 2950159, period: '2028' })
    } finally { Object.defineProperty(global, 'fetch', { configurable: true, value: old }) }
  })

})
