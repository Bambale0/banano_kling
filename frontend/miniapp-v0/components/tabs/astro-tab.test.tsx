import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    expect(screen.getByRole('status')).toHaveTextContent('данные не отправлены, баланс не списан')
  })

  it('collects two distinct birth profiles for compatibility', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Совместимость'))
    expect(screen.getByText('Первый человек')).toBeInTheDocument()
    expect(screen.getByText('Второй человек')).toBeInTheDocument()
    expect(screen.getByLabelText('person: дата рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('partner: дата рождения')).toBeInTheDocument()
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
      expect(screen.getByText(/2024-03-25/)).toBeInTheDocument()
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
    expect(screen.getByLabelText('Место встречи соляра')).toBeInTheDocument()
    expect(screen.getByLabelText('Период прогноза')).toHaveAttribute('type', 'number')
  })

})
