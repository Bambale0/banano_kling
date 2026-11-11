'use client'

import { useRef, useState } from 'react'
import { createVkInvoice, type VkNativeCommerce, type VkInvoiceResult, type VkInvoiceRequest } from '@/lib/shared-account-api'

type PaymentPackage = VkNativeCommerce['payment_packages'][number]

function safeCheckoutUrl(raw: unknown): string | null {
  if (typeof raw !== 'string' || raw.length > 2048) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'https:' && url.hostname && !url.username && !url.password && !url.hash
      ? url.href : null
  } catch { return null }
}

export function VkNativeCheckout({ packages }: { packages: PaymentPackage[] }) {
  const available = packages.filter(item => item.lava_offer_id && item.methods.some(m => m === 'lava_card' || m === 'lava_sbp'))
  const [packageId, setPackageId] = useState(available[0]?.id || '')
  const [method, setMethod] = useState<'CARD' | 'SBP'>('CARD')
  const [email, setEmail] = useState('')
  const [result, setResult] = useState<VkInvoiceResult | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const requestId = useRef('')

  if (!available.length) return null
  const chosen = available.find(p => p.id === packageId) || available[0]
  const methods = chosen.methods.filter(value => value === 'lava_card' || value === 'lava_sbp')
  const normalizedMethod = method === 'SBP' && methods.includes('lava_sbp') ? 'SBP'
    : methods.includes('lava_card') ? 'CARD' : 'SBP'
  const checkoutLink = result?.status === 'ready' ? safeCheckoutUrl(result.payment_url) : null

  const resetRequest = () => {
    requestId.current = ''
    setResult(null)
    setError('')
  }

  const createInvoice = async () => {
    if (loading || result?.status === 'ready' || result?.status === 'paid') return
    const normalizedEmail = email.trim().toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(normalizedEmail)) {
      setError('Укажите действительный email для чека.')
      return
    }
    if (!requestId.current) {
      // Never use predictable Math.random for financial idempotency tokens.
      if (!globalThis.crypto?.getRandomValues) {
        setError('Защищённое соединение недоступно. Откройте приложение повторно.')
        return
      }
      const bytes = crypto.getRandomValues(new Uint8Array(24))
      requestId.current = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
    }
    const payload: VkInvoiceRequest = {
      package_id: chosen.id, payment_method: normalizedMethod,
      customer_email: normalizedEmail, client_request_id: requestId.current,
    }
    setLoading(true)
    setError('')
    try {
      const response = await createVkInvoice(payload)
      setResult(response)
    } catch (cause) {
      // Retain requestId across a failed transport; user retry reuses the same
      // claim, never creates a second provider invoice for uncertain outcomes.
      setError(cause instanceof Error ? cause.message : 'Не удалось проверить счёт.')
    } finally {
      setLoading(false)
    }
  }

  return <form aria-label="Пополнение VK-баланса" className="space-y-3 rounded-xl border border-border/70 bg-card p-3"
    onSubmit={event => { event.preventDefault(); void createInvoice() }}>
    <h3 className="font-semibold">Пополнить баланс ВКонтакте</h3>
    <label className="block text-sm" htmlFor="vk-package">Пакет пополнения</label>
    <select id="vk-package" aria-label="Пакет пополнения" value={chosen.id} disabled={loading}
      onChange={event => { setPackageId(event.target.value); resetRequest() }}
      className="w-full rounded-lg border border-border bg-background p-2">
      {available.map(item => <option key={item.id} value={item.id}>{item.price_rub} ₽ · {item.credits} 🍌</option>)}
    </select>
    <label className="block text-sm" htmlFor="vk-method">Способ оплаты</label>
    <select id="vk-method" aria-label="Способ оплаты" value={normalizedMethod} disabled={loading}
      onChange={event => { setMethod(event.target.value as 'CARD' | 'SBP'); resetRequest() }}
      className="w-full rounded-lg border border-border bg-background p-2">
      {methods.includes('lava_card') && <option value="CARD">Карта</option>}
      {methods.includes('lava_sbp') && <option value="SBP">СБП</option>}
    </select>
    <label className="block text-sm" htmlFor="vk-email">Email для чека</label>
    <input id="vk-email" aria-label="Email для чека" type="email" required autoComplete="email" value={email}
      disabled={loading} onChange={event => { setEmail(event.target.value); resetRequest() }}
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
    {result?.status === 'paid' && <p role="status">Оплата подтверждена. Обновите баланс.</p>}
    {(result?.status === 'unknown' || result?.status === 'creating') &&
      <p role="status">Статус счёта уточняется. Повторный запрос использует тот же номер, новый счёт не создаётся.</p>}
  </form>
}
