'use client'

import { useEffect, useRef, useState } from 'react'

type Package = { id: string; name: string; price_rub: string; credits: string }
type Order = {
  order_id: string
  status: 'creating' | 'pending' | 'credited' | 'failed'
  payment_url: string | null
  amount_rub: string
  credits: string
}

export function WebPaymentsPanel({ onBalanceChanged }: { onBalanceChanged: () => void }) {
  const [packages, setPackages] = useState<Package[]>([])
  const [packageId, setPackageId] = useState('')
  const [email, setEmail] = useState('')
  const [order, setOrder] = useState<Order | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const checkoutKey = useRef('')

  useEffect(() => {
    const controller = new AbortController()
    void fetch('/mini-app/api/web-auth/web-payments/packages', {
      credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('Catalog unavailable')
      return await response.json() as { ok?: boolean; available?: boolean; packages?: Package[] }
    }).then(data => {
      if (!controller.signal.aborted && data.ok && data.available && data.packages?.length) {
        setPackages(data.packages)
        setPackageId(data.packages[0].id)
      }
    }).catch(() => {
      if (!controller.signal.aborted) setError('Не удалось загрузить актуальные цены.')
    })
    return () => controller.abort()
  }, [])

  const checkPayment = async (orderId: string) => {
    try {
      const url = '/mini-app/api/web-auth/web-payments/status?order_id=' + encodeURIComponent(orderId)
      const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' })
      if (!response.ok) return
      const result = await response.json() as Order & { ok?: boolean }
      if (!result.ok) return
      setOrder(result)
      if (result.status === 'credited') onBalanceChanged()
    } catch {
      // A status lookup outage cannot change a provider's actual payment state.
    }
  }

  useEffect(() => {
    if (!order || !['pending', 'creating'].includes(order.status)) return
    const timer = window.setInterval(() => { void checkPayment(order.order_id) }, 8000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order?.order_id, order?.status])

  const createPayment = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy || !packageId || !email.trim()) return
    setBusy(true)
    setError('')
    if (!checkoutKey.current) checkoutKey.current = crypto.randomUUID().replace(/-/g, '')
    try {
      const response = await fetch('/mini-app/api/web-auth/web-payments/create', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_key: checkoutKey.current, package_id: packageId, email: email.trim(),
        }),
      })
      const data = await response.json() as Partial<Order> & { ok?: boolean; error?: string }
      if (!response.ok || !data.ok || !data.order_id) {
        if (data.order_id) setOrder({
          order_id: data.order_id, status: 'creating', payment_url: null,
          amount_rub: '', credits: '',
        })
        throw new Error(data.error || 'Не удалось создать счёт.')
      }
      setOrder(data as Order)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось создать счёт.')
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-4 border border-[#a48350]/40 p-5" aria-label="Пополнение веб-баланса">
    <h2 className="text-xl font-bold">Пополнить веб-баланс</h2>
    <p className="text-sm text-[#bcb7af]">Lava, оплата в браузере. Средства поступят только
      после подтверждения оплаты и будут доступны этому аккаунту.</p>
    <form className="space-y-3" onSubmit={event => void createPayment(event)}>
      <label className="block text-sm text-[#d7c0a2]" htmlFor="web-payment-package">Пакет</label>
      <select id="web-payment-package" value={packageId}
        onChange={event => { setPackageId(event.target.value); checkoutKey.current = '' }}
        disabled={busy || !packages.length}
        className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-2 text-white">
        {packages.map(pack => <option key={pack.id} value={pack.id}>
          {pack.name} · {pack.price_rub} ₽ → {pack.credits} кредитов
        </option>)}
      </select>
      <label className="block text-sm text-[#d7c0a2]" htmlFor="web-payment-email">
        Почта для чека
      </label>
      <input id="web-payment-email" type="email" required autoComplete="email"
        maxLength={254} value={email} disabled={busy}
        onChange={event => { setEmail(event.target.value); checkoutKey.current = '' }}
        className="min-h-11 w-full border border-[#a48350] bg-[#151b1b] p-3 text-white" />
      <button type="submit" disabled={busy || !packageId || !email.trim()}
        className="min-h-11 w-full border border-[#b89454] bg-[#d5ab63] p-2 font-bold text-[#17120d] disabled:opacity-50">
        {busy ? 'Создаём безопасный счёт…' : 'Перейти к пополнению'}
      </button>
    </form>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    {order ? <div className="space-y-3 border border-[#a48350]/40 p-3">
      <p role="status" className="text-sm">Статус оплаты: {
        order.status === 'credited' ? 'зачислено' :
        order.status === 'failed' ? 'не завершена' :
        order.status === 'creating' ? 'подтверждаем счёт' : 'ожидаем оплату'
      }</p>
      {order.payment_url && order.status === 'pending' ? <a href={order.payment_url}
        target="_blank" rel="noopener noreferrer"
        className="inline-flex min-h-11 items-center border border-[#d6ad64] px-4 text-[#e9c684] underline">
        Открыть страницу оплаты Lava
      </a> : null}
      <button type="button" onClick={() => void checkPayment(order.order_id)}
        className="min-h-11 border border-[#8c7658] px-4 text-sm text-white">
        Проверить оплату
      </button>
      {order.status === 'credited' ? <p className="text-sm text-[#cdeab9]">
        Баланс пополнен на {order.credits} кредитов.
      </p> : null}
      {order.status === 'credited' || order.status === 'failed' ? (
        <button type="button" className="min-h-11 border border-[#8c7658] px-4 text-sm text-white"
          onClick={() => {
            setOrder(null)
            setError('')
            checkoutKey.current = ''
          }}>Создать новый счёт</button>
      ) : null}
    </div> : null}
  </section>
}
