'use client'

import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  createCommercialQuote, fetchCommercialCatalog, fetchCommercialTerms, fetchOwnCommercialTerms, findCommercialAccount,
  saveCommercialCatalog, saveCommercialTerms,
  type CommercialCatalog, type CommercialQuote, type CommercialTarget,
} from '@/lib/shared-account-api'

const inputClass = 'mt-1 w-full rounded border border-border bg-background p-2'
export function SharedCommercialPreview() {
  const [catalog, setCatalog] = useState<CommercialCatalog | null>(null)
  const [target, setTarget] = useState<CommercialTarget | null>(null)
  const [effectiveFresh, setEffectiveFresh] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [tariffId, setTariffId] = useState('')
  const [tariffLabel, setTariffLabel] = useState('')
  const [priceKey, setPriceKey] = useState('')
  const [amount, setAmount] = useState('')
  const [unit, setUnit] = useState<'job' | 'second'>('job')
  const [defaultTariff, setDefaultTariff] = useState(false)
  const [groupId, setGroupId] = useState('')
  const [groupLabel, setGroupLabel] = useState('')
  const [firstRate, setFirstRate] = useState('')
  const [secondRate, setSecondRate] = useState('')
  const [repeatReward, setRepeatReward] = useState('')
  const [defaultGroup, setDefaultGroup] = useState(false)
  const [platform, setPlatform] = useState<'telegram' | 'vk'>('vk')
  const [externalId, setExternalId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [quote, setQuote] = useState<CommercialQuote | null>(null)
  const operation = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    operation.current = controller
    Promise.all([fetchCommercialCatalog(controller.signal), fetchOwnCommercialTerms(controller.signal)])
      .then(([next, own]) => { if (!controller.signal.aborted) { setCatalog(next); setTarget(own) } })
      .catch(error => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Не удалось загрузить настройки.') })
    return () => operation.current?.abort()
  }, [])

  async function run(action: (signal: AbortSignal) => Promise<void>) {
    operation.current?.abort()
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setMessage('')
    setQuote(null)
    try { await action(controller.signal) }
    catch (error) { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : 'Попробуйте ещё раз.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }

  function editTerms(field: Exclude<keyof CommercialTarget['settings'], 'revision'>, value: string) {
    setTarget(previous => previous ? { ...previous, settings: { ...previous.settings, [field]: value || null } } : null)
  }

  async function applyCatalog(next: CommercialCatalog, signal: AbortSignal) {
    setCatalog(next)
    if (target) {
      setEffectiveFresh(false)
      const current = await fetchCommercialTerms(target.account_id, signal)
      // Refresh saved effective values, preserving the unsaved form and its CAS
      // revision. A concurrent administrator edit must still reject this draft.
      setTarget(previous => previous?.account_id === target.account_id ? { ...previous, effective: current.effective } : previous)
      setEffectiveFresh(true)
    }
  }

  async function reload(signal: AbortSignal) {
    const [next, selected] = await Promise.all([fetchCommercialCatalog(signal), target ? fetchCommercialTerms(target.account_id, signal) : fetchOwnCommercialTerms(signal)])
    setCatalog(next); setTarget(selected); setEffectiveFresh(true); setMessage('Настройки обновлены.')
  }

  if (!catalog) return <section aria-label="Тарифы и партнёрские условия"><p role="status">{message || 'Загрузка тарифов…'}</p>{message ? <Button disabled={busy} onClick={() => void run(reload)}>Повторить загрузку</Button> : null}</section>
  return <section aria-label="Тарифы и партнёрские условия" className="space-y-4 rounded-lg border border-border p-3">
    <h4 className="font-semibold">Общие тарифы и партнёрские условия</h4>
    <p className="text-xs text-muted-foreground">Администраторская проверка. Здесь настраивается новый общий каталог; действующие цены и начисления ботов пока не переключены.</p>
    <Button variant="outline" disabled={busy} onClick={() => void run(reload)}>Обновить настройки</Button>
    <fieldset disabled={busy} className="space-y-2 rounded border border-border p-3">
      <legend>Цена фото или видео</legend>
      <label className="block text-sm">Код тарифа<input className={inputClass} value={tariffId} onChange={event => setTariffId(event.target.value)} /></label>
      <label className="block text-sm">Название тарифа<input className={inputClass} value={tariffLabel} onChange={event => setTariffLabel(event.target.value)} /></label>
      <label className="block text-sm">Позиция прайса<input className={inputClass} value={priceKey} onChange={event => setPriceKey(event.target.value)} /></label>
      <label className="block text-sm">Стоимость в бананах<input className={inputClass} inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} /></label>
      <label className="block text-sm">Единица цены<select aria-label="Единица цены" className={inputClass} value={unit} onChange={event => setUnit(event.target.value as 'job' | 'second')}><option value="job">За генерацию</option><option value="second">За секунду</option></select></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={defaultTariff} onChange={event => setDefaultTariff(event.target.checked)} />Тариф по умолчанию</label>
      <Button disabled={!tariffId.trim() || !tariffLabel.trim() || !priceKey.trim() || !amount.trim()} onClick={() => void run(async signal => {
        const id = tariffId.trim(), position = priceKey.trim()
        const next = await saveCommercialCatalog({ ...catalog,
          default_tariff_id: defaultTariff ? id : catalog.default_tariff_id,
          tariffs: { ...catalog.tariffs, [id]: { label: tariffLabel.trim(), prices: {
            ...catalog.tariffs[id]?.prices, [position]: { amount: amount.trim().replace(',', '.'), unit },
          } } },
        }, signal)
        await applyCatalog(next, signal); setMessage('Цена сохранена в общем каталоге.')
      })}>Сохранить цену</Button>
      <ul aria-label="Общий прайс" className="space-y-1 text-sm">{Object.entries(catalog.tariffs).flatMap(([id, tariff]) => Object.entries(tariff.prices).map(([position, price]) =>
        <li key={id + ':' + position}><button type="button" className="text-left underline" onClick={() => {
          setTariffId(id); setTariffLabel(tariff.label); setPriceKey(position); setAmount(price.amount); setUnit(price.unit); setDefaultTariff(catalog.default_tariff_id === id)
        }}>{tariff.label}: {position} — {price.amount} ({price.unit === 'second' ? 'секунда' : 'генерация'})</button></li>))}</ul>
    </fieldset>
    <fieldset disabled={busy} className="space-y-2 rounded border border-border p-3">
      <legend>Партнёрская группа</legend>
      <label className="block text-sm">Код группы<input className={inputClass} value={groupId} onChange={event => setGroupId(event.target.value)} /></label>
      <label className="block text-sm">Название группы<input className={inputClass} value={groupLabel} onChange={event => setGroupLabel(event.target.value)} /></label>
      <label className="block text-sm">Процент первого уровня<input className={inputClass} inputMode="decimal" value={firstRate} onChange={event => setFirstRate(event.target.value)} /></label>
      <label className="block text-sm">Процент второго уровня<input className={inputClass} inputMode="decimal" value={secondRate} onChange={event => setSecondRate(event.target.value)} /></label>
      <label className="block text-sm">Вознаграждение за повтор, ₽<input className={inputClass} inputMode="decimal" value={repeatReward} onChange={event => setRepeatReward(event.target.value)} /></label>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={defaultGroup} onChange={event => setDefaultGroup(event.target.checked)} />Группа по умолчанию</label>
      <Button disabled={!groupId || !groupLabel || !firstRate || !secondRate || !repeatReward} onClick={() => void run(async signal => {
        const id = groupId.trim()
        const next = await saveCommercialCatalog({ ...catalog, default_partner_group_id: defaultGroup ? id : catalog.default_partner_group_id,
          partner_groups: { ...catalog.partner_groups, [id]: { label: groupLabel.trim(), first_level_percent: firstRate.replace(',', '.'), second_level_percent: secondRate.replace(',', '.'), repeat_reward_rub: repeatReward.replace(',', '.') } },
        }, signal)
        await applyCatalog(next, signal); setMessage('Партнёрская группа сохранена.')
      })}>Сохранить группу</Button>
      <ul className="text-sm">{Object.entries(catalog.partner_groups).map(([id, group]) => <li key={id}><button type="button" className="text-left underline" onClick={() => {
        setGroupId(id); setGroupLabel(group.label); setFirstRate(group.first_level_percent); setSecondRate(group.second_level_percent); setRepeatReward(group.repeat_reward_rub); setDefaultGroup(catalog.default_partner_group_id === id)
      }}>{group.label}: {group.first_level_percent}% / {group.second_level_percent}%; повтор {group.repeat_reward_rub} ₽</button></li>)}</ul>
    </fieldset>
    <fieldset disabled={busy} className="space-y-2 rounded border border-border p-3">
      <legend>Индивидуальные условия аккаунта</legend>
      <label className="block text-sm">Платформа аккаунта<select aria-label="Платформа аккаунта" className={inputClass} value={platform} onChange={event => setPlatform(event.target.value as 'telegram' | 'vk')}><option value="vk">ВК</option><option value="telegram">ТГ</option></select></label>
      <label className="block text-sm">ID пользователя<input className={inputClass} inputMode="numeric" value={externalId} onChange={event => setExternalId(event.target.value)} /></label>
      <Button variant="outline" disabled={!externalId} onClick={() => void run(async signal => { setTarget(await findCommercialAccount(platform, externalId.trim(), signal)); setEffectiveFresh(true); setMessage('Аккаунт найден.') })}>Найти аккаунт</Button>
      {target ? <>
        <p className="break-all text-xs">Выбран аккаунт: {target.account_id}</p>
        <label className="block text-sm">Тариф аккаунта<select aria-label="Тариф аккаунта" className={inputClass} value={target.settings.tariff_id || ''} onChange={event => editTerms('tariff_id', event.target.value)}><option value="">По умолчанию</option>{Object.entries(catalog.tariffs).map(([id, tariff]) => <option key={id} value={id}>{tariff.label}</option>)}</select></label>
        <label className="block text-sm">Группа аккаунта<select aria-label="Группа аккаунта" className={inputClass} value={target.settings.partner_group_id || ''} onChange={event => editTerms('partner_group_id', event.target.value)}><option value="">По умолчанию</option>{Object.entries(catalog.partner_groups).map(([id, group]) => <option key={id} value={id}>{group.label}</option>)}</select></label>
        <p className="text-xs text-muted-foreground">Пустое индивидуальное поле использует ставку группы; 0 — отдельное условие без начисления.</p>
        {(['first_level_percent', 'second_level_percent', 'repeat_reward_rub'] as const).map((field, index) => <label key={field} className="block text-sm">{['Индивидуальный процент первого уровня', 'Индивидуальный процент второго уровня', 'Индивидуальное вознаграждение за повтор, ₽'][index]}<input className={inputClass} inputMode="decimal" value={target.settings[field] ?? ''} onChange={event => editTerms(field, event.target.value.replace(',', '.'))} /></label>)}
        <Button onClick={() => void run(async signal => { setTarget(await saveCommercialTerms(target, signal)); setEffectiveFresh(true); setMessage('Индивидуальные условия сохранены.') })}>Сохранить условия аккаунта</Button>
        {effectiveFresh ? <p className="text-sm">Действующая ставка: {target.effective.first_level_percent ?? 'не настроена'}%. Повтор: {target.effective.repeat_reward_rub ?? 'не настроен'} ₽.</p> : <p className="text-sm">Действующие условия нужно обновить.</p>}
      </> : null}
    </fieldset>
    <fieldset disabled={busy} className="space-y-2 rounded border border-border p-3">
      <legend>Проверить расчёт для своего аккаунта</legend>
      <label className="block text-sm">Позиция для расчёта<input className={inputClass} value={priceKey} onChange={event => setPriceKey(event.target.value)} /></label>
      <label className="block text-sm">Количество секунд или один запуск<input className={inputClass} inputMode="numeric" value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
      <Button disabled={!priceKey} onClick={() => void run(async signal => {
        if (!/^[1-9][0-9]*$/.test(quantity) || !Number.isSafeInteger(Number(quantity))) throw new Error('Укажите целое количество.')
        setQuote(await createCommercialQuote(priceKey, Number(quantity), signal))
      })}>Рассчитать стоимость</Button>
      {quote ? <p role="status">Стоимость: {quote.total} банана. Ставка: {quote.terms.first_level_percent ?? 'не настроена'}%.{quote.platform === 'vk' ? ' Для ВК предусмотрена только Lava.' : ''}</p> : null}
    </fieldset>
    {message ? <p role="status">{message}</p> : null}
  </section>
}
