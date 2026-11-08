import { fireEvent, render, screen } from '@testing-library/react'
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
  it('requests the solar-return location separately from birthplace', () => {
    render(<AstroTab />)
    fireEvent.click(screen.getByText('Соляр'))
    expect(screen.getByLabelText('person: место рождения')).toBeInTheDocument()
    expect(screen.getByLabelText('Место встречи соляра')).toBeInTheDocument()
    expect(screen.getByLabelText('Период прогноза')).toHaveAttribute('type', 'number')
  })

})
