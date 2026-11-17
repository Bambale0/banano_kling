import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { AstroChartWheel } from './astro-chart-wheel'

describe('AstroChartWheel: verified positions, not a decorative horoscope', () => {
  const chart = {
    bodies: {
      Sun: { lon: 0, retro: false },
      Moon: { lon: 89.9, retro: false },
      Mercury: { lon: 355, retro: true },
    },
    angles: { asc: 25, mc: 295 },
    cusps: Array.from({ length: 12 }, (_, index) => (25 + 30 * index) % 360),
    aspects: [{ a: 'Sun', b: 'Moon', aspect: 'square', orb: 0.1 }],
  }

  it('draws twelve zodiac sectors, calculated houses, bodies, aspects and angles', () => {
    render(<AstroChartWheel chart={chart} label="Рассчитанная натальная карта" />)
    const wheel = screen.getByRole('img', { name: 'Рассчитанная натальная карта' })
    expect(wheel).toHaveAttribute('viewBox', '0 0 440 440')
    expect(wheel.querySelectorAll('[data-astro-zodiac-sign]')).toHaveLength(12)
    expect(wheel.querySelectorAll('[data-astro-house-cusp]')).toHaveLength(12)
    expect(wheel.querySelectorAll('[data-astro-body]')).toHaveLength(3)
    expect(wheel.querySelector('[data-astro-body="Sun"]')).toHaveAttribute('data-longitude', '0')
    expect(wheel.querySelector('[data-astro-body="Mercury"]')).toHaveAttribute('data-longitude', '355')
    expect(wheel.querySelector('[data-astro-aspect="Sun-Moon"]')).toBeInTheDocument()
    expect(wheel.querySelector('[data-astro-angle="asc"]')).toBeInTheDocument()
    expect(wheel.querySelector('[data-astro-angle="mc"]')).toBeInTheDocument()
  })

  it('never invents a house system, angles, or Moon when birth time is unknown', () => {
    render(<AstroChartWheel chart={{
      bodies: { Sun: { lon: 330.1 } },
      angles: null, cusps: null, aspects: [{ a: 'Sun', b: 'Moon', aspect: 'square', orb: 1 }],
    }} label="Неполная карта" />)
    const wheel = screen.getByRole('img', { name: 'Неполная карта' })
    expect(wheel.querySelectorAll('[data-astro-house-cusp]')).toHaveLength(0)
    expect(wheel.querySelectorAll('[data-astro-angle]')).toHaveLength(0)
    expect(wheel.querySelectorAll('[data-astro-aspect]')).toHaveLength(0)
    expect(wheel.querySelectorAll('[data-astro-body]')).toHaveLength(1)
    expect(screen.getByText(/Дома и углы отсутствуют/)).toBeInTheDocument()
  })

  it('rejects invalid numerical positions instead of drawing invented objects', () => {
    render(<AstroChartWheel chart={{
      bodies: { Sun: { lon: Number.NaN }, Mercury: { lon: 120 } },
      angles: null, cusps: [10, 20] }, label="Неполные данные" />)
    const wheel = screen.getByRole('img', { name: 'Неполные данные' })
    expect(wheel.querySelectorAll('[data-astro-body]')).toHaveLength(1)
    expect(wheel.querySelector('[data-astro-body="Sun"]')).not.toBeInTheDocument()
    expect(wheel.querySelectorAll('[data-astro-house-cusp]')).toHaveLength(0)
  })
})
