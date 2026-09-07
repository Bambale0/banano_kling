import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { DurationSelect } from '@/components/forms/duration-select'

describe('DurationSelect', () => {
  it('uses a slider for long duration lists and filters invalid values', () => {
    render(
      <DurationSelect
        durations={[
          -1,
          4, 5, 6, 7, 8, 9, 10,
          11, 12, 13, 14, 15,
          16, 17, 18, 19, 20,
          21, 22, 23, 24, 25,
          26, 27, 28, 29, 30,
        ]}
        value={25}
        onChange={jest.fn()}
        costs={{ '25': 150 }}
      />
    )

    expect(screen.getByRole('slider', { name: 'Длительность видео' })).toBeInTheDocument()
    expect(screen.queryByText('-1с')).not.toBeInTheDocument()
    expect(screen.getByText('4 сек')).toBeInTheDocument()
    expect(screen.getByText('30 сек')).toBeInTheDocument()
    expect(screen.getByText('25 сек')).toBeInTheDocument()
    expect(screen.getByText('6/с')).toBeInTheDocument()
  })

  it('maps slider positions to the real duration array', () => {
    const onChange = jest.fn()

    render(
      <DurationSelect
        durations={[4, 5, 6, 7, 8, 9]}
        value={4}
        onChange={onChange}
        costs={{}}
      />
    )

    const slider = screen.getByRole('slider', { name: 'Длительность видео' })
    fireEvent.change(slider, { target: { value: '3' } })

    expect(onChange).toHaveBeenLastCalledWith(7)
  })

  it('never invents intermediate values for sparse durations', () => {
    const onChange = jest.fn()

    render(
      <DurationSelect
        durations={[4, 8, 12, 20, 30, 60]}
        value={20}
        onChange={onChange}
        costs={{}}
      />
    )

    const slider = screen.getByRole('slider', { name: 'Длительность видео' })
    fireEvent.change(slider, { target: { value: '4' } })

    expect(onChange).toHaveBeenLastCalledWith(30)
    expect(onChange).not.toHaveBeenCalledWith(21)
  })

  it('keeps compact buttons for short duration lists', () => {
    render(
      <DurationSelect
        durations={[5, 10, 15]}
        value={10}
        onChange={jest.fn()}
        costs={{ '5': 10, '10': 20, '15': 30 }}
      />
    )

    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(3)
    expect(screen.getByText('5с')).toBeInTheDocument()
    expect(screen.getByText('10с')).toBeInTheDocument()
    expect(screen.getByText('15с')).toBeInTheDocument()
  })

  it('does not render fake zero, NaN, or Infinity pricing when costs are missing', () => {
    render(
      <DurationSelect
        durations={[5, 10, 15]}
        value={10}
        onChange={jest.fn()}
        costs={{}}
      />
    )

    expect(screen.queryByText(/0\/с/)).not.toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Infinity/)).not.toBeInTheDocument()
  })

  it('filters garbage durations before rendering controls', () => {
    render(
      <DurationSelect
        durations={[-1, 0, Number.NaN, 5, 10]}
        value={5}
        onChange={jest.fn()}
        costs={{}}
      />
    )

    expect(screen.getAllByRole('button')).toHaveLength(2)
    expect(screen.getByText('5с')).toBeInTheDocument()
    expect(screen.getByText('10с')).toBeInTheDocument()
    expect(screen.queryByText('-1с')).not.toBeInTheDocument()
    expect(screen.queryByText('0с')).not.toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })

  it('renders nothing when no valid duration remains', () => {
    const onChange = jest.fn()
    const { container } = render(
      <DurationSelect
        durations={[-1, 0, Number.NaN, Number.POSITIVE_INFINITY]}
        value={5}
        onChange={onChange}
        costs={{}}
      />
    )

    expect(container).toBeEmptyDOMElement()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('synchronizes an unsupported value to the nearest valid duration after render', async () => {
    const onChange = jest.fn()

    render(
      <DurationSelect
        durations={[4, 8, 12, 20, 30, 60]}
        value={22}
        onChange={onChange}
        costs={{}}
      />
    )

    expect(screen.getByText('20 сек')).toBeInTheDocument()
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(20))
  })
})
