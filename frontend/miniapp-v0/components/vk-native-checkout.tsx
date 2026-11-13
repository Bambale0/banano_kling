'use client'

import { useRef, useState } from 'react'
import { createVkInvoice, type VkNativeCommerce, type VkInvoiceResult, type VkInvoiceRequest } from '@/lib/shared-account-api'

type PaymentPackage = VkNativeCommerce['payment_packages'][number]

export type VkCheckoutAttempt = {
  request: VkInvoiceRequest
  result: VkInvoiceResult | null
  error: string
}

function safeCheckoutUrl(raw: unknown): string | null {
  if (typeof raw !== 'string' || raw.length > 2048) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'https:' && url.hostname && !url.username && !url.password && !url.hash
      ? url.href : null
  } catch { return null }
}

export function VkNativeCheckout({ packages, attempt, onAttemptChange }: {
  packages: PaymentPackage[]
  attempt: VkCheckoutAttempt | null
  onAttemptChange: (attempt: VkCheckoutAttempt | null) => void
}) {
  const available = packages.filter(item => item.lava_offer_id && item.methods.some(m => m === 'lava_card' || m === 'lava_sbp'))
  const [packageId, setPackageId] = useState(attempt?.request.package_id || available[0]?.id || '')
  const [method, setMethod] = useState<'CARD' | 'SBP'>(attempt?.request.payment_method || 'CARD')
  const [email, setEmail] = useState(attempt?.request.customer_email || '')
  const [result, setResult] = useState<VkInvoiceResult | null>(attempt?.result || null)
  const [error, setError] = useState(attempt?.error || '')
  const [loading, setLoading] = useState(false)
  const requestId = useRef(attempt?.request.client_request_id || '')
  // A provider may have accepted the first request despite a timeout.
  // Until the invoice is reconciled, never allow a different payload with a
  // fresh idempotency key from this checkout instance.
  const termsLocked = loading || attempt !== null

  if (!available.length) return null
  if (attempt && !available.some(item => item.id === attempt.request.package_id
    && item.methods.includes(attempt.request.payment_method === 'CARD' ? 'lava_card' : 'lava_sbp'))) {
    return <p role="alert">Условия прежнего счёта изменились. Проверьте его статус перед новым пополнением.</p>
  }
  const chosen = available.find(p => p.id === packageId) || available[0]
  const methods = chosen.methods.filter(value => value === 'lava_card' || value === 'lava_sbp')
  const normalizedMethod = method === 'SBP' && methods.includes('lava_sbp') ? 'SBP'
    : methods.includes('lava_card') ? 'CARD' : 'SBP'
  const checkoutLink = result?.status === 'ready' ? safeCheckoutUrl(result.payment_url) : null

  const resetRequest = () => {
    requestId.current = ''
    setResult(null)
    setError('')
    onAttemptChange(null)
  }

  const createInvoice = async () => {
    if (loading || result?.status === 'ready' || result?.status === 'paid') return
    const normalizedEmail = email.trim().toLowerCase()
    if (!attempt && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalizedEmail)) {
      setError('Укажите действительный email для чека.')
      return
    }
    if (!attempt && !requestId.current) {
      // Never use predictable Math.random for financial idempotency tokens.
      if (!globalThis.crypto?.getRandomValues) {
        setError('Защищённое соединение недоступно. Откройте приложение повторно.')
        return
      }
      const bytes = crypto.getRandomValues(new Uint8Array(24))
      requestId.current = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
    }
    // Retries must carry the byte-for-byte original financial intent.
    const payload: VkInvoiceRequest = attempt?.request || {
      package_id: chosen.id, payment_method: normalizedMethod,
      customer_email: normalizedEmail, client_request_id: requestId.current,
    }
    setLoading(true)
    setError('')
    try {
      const response = await createVkInvoice(payload)
      setResult(response)
      onAttemptChange({ request: payload, result: response, error: '' })
    } catch (cause) {
      // Retain requestId across a failed transport; user retry reuses the same
      // claim, never creates a second provider invoice for uncertain outcomes.
      const message = cause instanceof Error ? cause.message : 'Не удалось проверить счёт.'
      setError(message)
      onAttemptChange({ request: payload, result: null, error: message })
    } finally {
      setLoading(false)
    }
  }

  return <form aria-label="Пополнение VK-баланса" className="space-y-3 rounded-xl border border-border/70 bg-card p-3"
    onSubmit={event => { event.preventDefault(); void createInvoice() }}>
    <h3 className="font-semibold">Пополнить баланс ВКонтакте</h3>
    <label className="block text-sm" htmlFor="vk-package">Пакет пополнения</label>
    <select id="vk-package" aria-label="Пакет пополнения" value={chosen.id} disabled={termsLocked}
      onChange={event => { setPackageId(event.target.value); resetRequest() }}
      className="w-full rounded-lg border border-border bg-background p-2">
      {available.map(item => <option key={item.id} value={item.id}>{item.price_rub} ₽ · {item.credits} 🍌</option>)}
    </select>
    <label className="block text-sm" htmlFor="vk-method">Способ оплаты</label>
    <select id="vk-method" aria-label="Способ оплаты" value={normalizedMethod} disabled={termsLocked}
      onChange={event => { setMethod(event.target.value as 'CARD' | 'SBP'); resetRequest() }}
      className="w-full rounded-lg border border-border bg-background p-2">
      {methods.includes('lava_card') && <option value="CARD">Карта</option>}
      {methods.includes('lava_sbp') && <option value="SBP">СБП</option>}
    </select>
    <label className="block text-sm" htmlFor="vk-email">Email для чека</label>
    <input id="vk-email" aria-label="Email для чека" type="email" required autoComplete="email" value={email}
      disabled={termsLocked} onChange={event => { setEmail(event.target.value); resetRequest() }}
      className="w-full rounded-lg border border-border bg-background p-2" />
    {!result || result.status === 'unknown' || result.status === 'creating'
      ? <button type="submit" disabled={loading}
          className="w-full rounded-lg bg-primary p-3 font-semibold text-primary-foreground">
          {loading ? 'Проверяем счёт…' : 'Получить ссылку на оплату'}
        </button> : null}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {checkoutLink && <div className="space-y-2">
      <p role="status" className="text-sm">Счёт подготовлен. Баланс изменится только после подтверждения оплаты.</p>
      <a href={checkoutLink} target="_blank" rel="noopener noreferrer"
        className="block rounded-lg bg-primary p-3 text-center font-semibold text-primary-foreground">
        Перейти к оплате Lava
      </a>
    </div>}
    {result?.status === 'paid' && <div className="space-y-2">
      <p role="status">Оплата подтверждена. Обновите баланс.</p>
      <button type="button" onClick={resetRequest}
        className="w-full rounded-lg border border-border p-3 text-sm font-semibold">
        Начать новое пополнение
      </button>
    </div>}
    {(result?.status === 'unknown' || result?.status === 'creating') &&
      <p role="status">Статус счёта уточняется. Повторный запрос использует тот же номер, новый счёт не создаётся.</p>}
  </form>
}
