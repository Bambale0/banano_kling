import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Wan3PrimeForm } from '@/components/forms/wan3-prime-form'
import * as wanApi from '@/lib/wan3-prime-api'

jest.mock('@/lib/api', () => ({ getApiBasePath: () => '/api', getInitData: () => 'signed', getStartParamFallback: () => '' }), { virtual: true })
jest.mock('@/lib/wan3-prime-api', () => ({
  ...jest.requireActual('@/lib/wan3-prime-api'),
  fetchWan3PrimeTrendPlan: jest.fn(), fetchWan3PrimeRepeatPlan: jest.fn(), fetchWan3PrimeOwnerRecipe: jest.fn(),
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(), uploadWan3PrimeReference: jest.fn(), importWan3PrimeReference: jest.fn(),
}))
const mocked = wanApi as jest.Mocked<typeof wanApi>
beforeEach(() => { jest.clearAllMocks(); mocked.quoteWan3Prime.mockResolvedValue({ ok: true, quote_hash: 'q', reserve_cost: 1 } as any) })

test('an unavailable WAN repeat shows a retryable safe error, never a blank text composer', async () => {
  mocked.fetchWan3PrimeTrendPlan.mockRejectedValue(new wanApi.Wan3PrimeApiError('private upstream details', 'validation_error', 404))
  render(<Wan3PrimeForm credits={10} trendId={2043} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Тренд недоступен для повтора')
  expect(screen.getByRole('button', { name: 'Повторить загрузку рецепта' })).toBeEnabled()
  expect(screen.queryByLabelText('Инструкции Wan')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  expect(mocked.quoteWan3Prime).not.toHaveBeenCalled()
})

const recipe = (model: wanApi.Wan3PrimeRecipe['model'] = 'wan_3'): wanApi.Wan3PrimeRecipe => ({ model, scenario: 'reference', prompt: '', resolution: '720P', aspect_ratio: '9:16', duration: 8, audio: true, nsfw_checker: true, seed: 42 })
const plan = (id: number): wanApi.Wan3PrimeRepeatPlan => ({ ok: true, trend_id: id, repeat_plan_hash: `hash${id}`, recipe: recipe(), slots: [] } as any)
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej }); return { promise, resolve, reject } }

test('retry restores the actual repeat settings; a late old trend never overwrites a newer one', async () => {
  const old = deferred<wanApi.Wan3PrimeRepeatPlan>()
  mocked.fetchWan3PrimeTrendPlan.mockRejectedValueOnce(new wanApi.Wan3PrimeApiError('secret', 'validation_error', 404))
    .mockImplementationOnce(() => old.promise).mockResolvedValueOnce(plan(22))
  const view = render(<Wan3PrimeForm credits={10} model="wan_3" trendId={21} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку рецепта' }))
  const signal = mocked.fetchWan3PrimeTrendPlan.mock.calls[1][1]!
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3" trendId={22} />)
  expect(signal.aborted).toBe(true)
  await screen.findByLabelText('Инструкции Wan')
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Only trend 22' } })
  await act(async () => old.resolve({ ...plan(21), recipe: { ...recipe(), resolution: '480P' } }))
  expect(screen.getByLabelText('Качество Wan')).toHaveValue('720P')
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('Only trend 22')
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3_prime" />)
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.getByRole('button', { name: 'По тексту' })).toHaveAttribute('aria-pressed', 'true')
})

test('owner and model navigation clear private references and ignore late owner responses', async () => {
  const own = deferred<wanApi.Wan3PrimeOwnerRecipeResponse>()
  mocked.fetchWan3PrimeOwnerRecipe.mockImplementationOnce(() => own.promise)
  const view = render(<Wan3PrimeForm credits={10} ownerTaskId="old" model="wan_3" />)
  const signal = mocked.fetchWan3PrimeOwnerRecipe.mock.calls[0][1]!
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3_prime" />)
  await act(async () => own.resolve({ ok: true, recipe: { ...recipe(), prompt: 'private old prompt', reference_image_urls: ['https://owned/private.png'] } }))
  expect(signal.aborted).toBe(true)
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.queryByText('private.png')).not.toBeInTheDocument()
})

test.each(['wan_3', 'wan_3_prime'] as const)('draft %s never quotes or generates and hides unsupported links', async model => {
  const onDraftChange = jest.fn()
  render(<Wan3PrimeForm credits={0} model={model} draftOnly onDraftChange={onDraftChange} />)
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Private prompt' } })
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)) })
  expect(onDraftChange).toHaveBeenLastCalledWith(expect.objectContaining({ recipe: expect.objectContaining({ model, prompt: 'Private prompt' }), issue: null, busy: false }))
  expect(screen.queryByRole('button', { name: 'Из веб-страницы' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Рассчитать стоимость' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  expect(screen.queryByRole('option', { name: 'Веб-страница' })).not.toBeInTheDocument()
  expect(screen.queryByText('Импортировать по ссылке')).not.toBeInTheDocument()
  expect(mocked.quoteWan3Prime).not.toHaveBeenCalled()
  expect(mocked.generateWan3Prime).not.toHaveBeenCalled()
})

test('safe errors hide remote details while local file validation and cancellation remain actionable', () => {
  for (const code of ['validation_error', 'wan_publication_invalid', 'unknown', '']) {
    expect(wanApi.wan3SafeError(new wanApi.Wan3PrimeApiError('provider secret 123', code, 500), 'Не удалось выполнить запрос.')).not.toMatch(/provider|secret|123/)
  }
  expect(wanApi.wan3SafeError(new Error('Wan 3.0 принимает этот тип файла до 20 MB.'), 'Ошибка')).toContain('20 MB')
  expect(wanApi.wan3SafeError(new DOMException('Aborted', 'AbortError'), 'Ошибка')).toContain('отменена')
  expect(wanApi.wan3SafeError(new Error('raw upstream details'), 'Не удалось загрузить файл.')).toBe('Не удалось загрузить файл.')
})

test('a successful retry opens the selected recipe with numbered upload slots', async () => {
  mocked.fetchWan3PrimeTrendPlan.mockRejectedValueOnce(new wanApi.Wan3PrimeApiError('secret', 'validation_error', 404)).mockResolvedValueOnce({
    ...plan(31), slots: [{ key: 'image:0', kind: 'image', index: 0, role: 'reference', binding: 'upload' }],
  })
  render(<Wan3PrimeForm credits={10} model="wan_3" trendId={31} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку рецепта' }))
  expect(await screen.findByLabelText('Загрузить Image1')).toBeInTheDocument()
  expect(screen.queryByText('Тренд недоступен для повтора. Попросите автора опубликовать его заново.')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Качество Wan')).toHaveValue('720P')
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
  expect(mocked.quoteWan3Prime).not.toHaveBeenCalled()
})

test('explicit model change rejects a stale private initial recipe', () => {
  const initialRecipe = { ...recipe(), prompt: 'Old private prompt', reference_image_urls: ['https://owned/private.png'] }
  const view = render(<Wan3PrimeForm credits={10} model="wan_3" initialRecipe={initialRecipe} />)
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('Old private prompt')
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3_prime" initialRecipe={initialRecipe} />)
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.queryByText('private.png')).not.toBeInTheDocument()
  expect(screen.getByText('Wan 3.0 Video Prime')).toBeInTheDocument()
})

test('the same initial recipe object on an ordinary rerender preserves edits and pending uploads', async () => {
  const initialRecipe = { ...recipe(), prompt: 'Saved recipe' }
  const pending = deferred<any>()
  mocked.uploadWan3PrimeReference.mockImplementationOnce(() => pending.promise)
  const view = render(<Wan3PrimeForm credits={10} initialRecipe={initialRecipe} />)
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'My changes' } })
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [new File(['x'], 'new.png', { type: 'image/png' })] } })
  await waitFor(() => expect(mocked.uploadWan3PrimeReference).toHaveBeenCalledTimes(1))
  const signal = mocked.uploadWan3PrimeReference.mock.calls[0][2]!
  view.rerender(<Wan3PrimeForm credits={11} initialRecipe={initialRecipe} />)
  expect(signal.aborted).toBe(false)
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('My changes')
  await act(async () => pending.resolve({ url: 'https://owned/new.png' }))
  expect(screen.getByText('new.png')).toBeInTheDocument()
})

test('normal generation keeps retrying the same accepted request and uses neutral launch text', async () => {
  mocked.generateWan3Prime.mockResolvedValue({ ok: true, status: 'unknown', internal_task_id: 'task-local', reserve_cost: 1 })
  render(<Wan3PrimeForm credits={10} initialRecipe={{ ...recipe(), scenario: 'text', prompt: 'Animate' }} />)
  const launch = screen.getByRole('button', { name: 'Запустить Wan' })
  await waitFor(() => expect(launch).toBeEnabled())
  fireEvent.click(launch)
  expect(await screen.findByText('Запуск ещё не подтверждён. Проверяем эту же задачу.')).toBeInTheDocument()
  expect(screen.queryByText(/провайдер/i)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Проверить запуск' }))
  await waitFor(() => expect(mocked.generateWan3Prime).toHaveBeenCalledTimes(2))
  expect(mocked.generateWan3Prime.mock.calls[0][0]).toEqual(mocked.generateWan3Prime.mock.calls[1][0])
})

test('an owner response for a different explicit model fails closed even with a valid initial recipe', async () => {
  mocked.fetchWan3PrimeOwnerRecipe.mockResolvedValueOnce({ ok: true, recipe: { ...recipe('wan_3_prime'), prompt: 'Wrong private model', reference_image_urls: ['https://owned/private.png'] } })
    .mockResolvedValueOnce({ ok: true, recipe: { ...recipe('wan_3'), prompt: 'Correct own recipe', reference_image_urls: ['https://owned/own.png'] } })
  render(<Wan3PrimeForm credits={10} model="wan_3" ownerTaskId="own-task" initialRecipe={{ ...recipe(), scenario: 'text', prompt: 'Valid initial prompt' }} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Настройки относятся к другой модели Wan')
  expect(screen.queryByLabelText('Инструкции Wan')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)) })
  expect(mocked.quoteWan3Prime).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку настроек' }))
  expect(await screen.findByLabelText('Инструкции Wan')).toHaveValue('Correct own recipe')
  expect(screen.getByText('own.png')).toBeInTheDocument()
  expect(screen.queryByText('private.png')).not.toBeInTheDocument()
})

test('a repeat plan for a different explicit model fails closed before storing its recipe', async () => {
  mocked.fetchWan3PrimeTrendPlan.mockResolvedValueOnce({ ...plan(41), recipe: { ...recipe('wan_3_prime'), prompt: 'Wrong recipe', reference_image_urls: ['https://owned/wrong.png'] } })
    .mockResolvedValueOnce(plan(41))
  render(<Wan3PrimeForm credits={10} model="wan_3" trendId={41} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Рецепт относится к другой модели Wan')
  expect(screen.queryByLabelText('Инструкции Wan')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  expect(mocked.quoteWan3Prime).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку рецепта' }))
  expect(await screen.findByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.getByText('Wan 3.0 Video')).toBeInTheDocument()
  expect(screen.queryByText('wrong.png')).not.toBeInTheDocument()
})

test.each([false, true])('a same-source restore during an unknown launch preserves the frozen request (changed content: %s)', async changedContent => {
  const initialRecipe = { ...recipe(), scenario: 'text' as const, prompt: 'Animate this' }
  mocked.generateWan3Prime.mockResolvedValue({ ok: true, status: 'unknown', internal_task_id: 'task-unknown', reserve_cost: 1 })
  const view = render(<Wan3PrimeForm credits={10} model="wan_3" initialRecipe={initialRecipe} />)
  const launch = screen.getByRole('button', { name: 'Запустить Wan' })
  await waitFor(() => expect(launch).toBeEnabled())
  fireEvent.click(launch)
  await screen.findByText('Запуск ещё не подтверждён. Проверяем эту же задачу.')
  const frozen = mocked.generateWan3Prime.mock.calls[0][0]
  const quoted = mocked.quoteWan3Prime.mock.calls.length
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3" initialRecipe={{ ...initialRecipe, ...(changedContent ? { prompt: 'Different instructions', duration: 12 } : {}) }} />)
  expect(screen.getByRole('button', { name: 'Проверить запуск' })).toBeEnabled()
  expect(screen.getByLabelText('Инструкции Wan')).toBeDisabled()
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('Animate this')
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)) })
  expect(mocked.quoteWan3Prime).toHaveBeenCalledTimes(quoted)
  fireEvent.click(screen.getByRole('button', { name: 'Проверить запуск' }))
  await waitFor(() => expect(mocked.generateWan3Prime).toHaveBeenCalledTimes(2))
  expect(mocked.generateWan3Prime.mock.calls[1][0]).toBe(frozen)
})

test('unchanged explicit trend source ignores fallback recipe ID changes during an unknown launch', async () => {
  mocked.fetchWan3PrimeTrendPlan.mockResolvedValue(plan(41))
  mocked.generateWan3Prime.mockResolvedValue({ ok: true, status: 'unknown', internal_task_id: 'task-explicit-trend', reserve_cost: 1 })
  const initialRecipe = { ...recipe(), trend_id: 77, source_feed_gen_id: 88 }
  const view = render(<Wan3PrimeForm credits={10} model="wan_3" trendId={41} initialRecipe={initialRecipe} />)
  const launch = await screen.findByRole('button', { name: 'Запустить Wan' })
  await waitFor(() => expect(launch).toBeEnabled())
  fireEvent.click(launch)
  await screen.findByText('Запуск ещё не подтверждён. Проверяем эту же задачу.')
  const frozen = mocked.generateWan3Prime.mock.calls[0][0]
  const quoted = mocked.quoteWan3Prime.mock.calls.length
  expect(frozen.recipe.trend_id).toBe(41)
  view.rerender(<Wan3PrimeForm credits={10} model="wan_3" trendId={41} initialRecipe={{ ...initialRecipe, trend_id: 99, source_feed_gen_id: 100 }} />)
  expect(screen.getByRole('button', { name: 'Проверить запуск' })).toBeEnabled()
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 400)) })
  expect(mocked.fetchWan3PrimeTrendPlan).toHaveBeenCalledTimes(1)
  expect(mocked.quoteWan3Prime).toHaveBeenCalledTimes(quoted)
  fireEvent.click(screen.getByRole('button', { name: 'Проверить запуск' }))
  await waitFor(() => expect(mocked.generateWan3Prime).toHaveBeenCalledTimes(2))
  expect(mocked.generateWan3Prime.mock.calls[1][0]).toBe(frozen)
})
