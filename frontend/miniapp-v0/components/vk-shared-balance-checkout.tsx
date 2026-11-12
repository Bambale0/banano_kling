'use client'

import { useEffect, useState } from 'react'
import { fetchVkNativeCommerce, type VkNativeCommerce } from '@/lib/shared-account-api'
import { VkNativeCheckout, type VkCheckoutAttempt } from '@/components/vk-native-checkout'

/** Platform-owned commerce inside the SAME shared BalanceSheet, not Telegram's ledger. */
export function VkSharedBalanceCheckout({ isOpen, attempt, onAttemptChange }: {
  isOpen: boolean
  attempt: VkCheckoutAttempt | null
  onAttemptChange: (value: VkCheckoutAttempt | null) => void
}) {
  const [commerce, setCommerce] = useState<VkNativeCommerce | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    const controller = new AbortController()
    setCommerce(null)
    setLoading(true)
    setError('')
    fetchVkNativeCommerce(controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setCommerce(data)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('Не удалось проверить оплату ВКонтакте. Повторите позже.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [isOpen])

  if (loading) return <p role="status">Проверяем доступные способы оплаты ВКонтакте…</p>
  if (error) return <p role="alert">{error}</p>
  if (!commerce?.registered) return <p role="status">Оплата ВКонтакте пока недоступна.</p>
  if (commerce.payments_enabled !== true) {
    return <p role="status">Пополнение ВКонтакте временно недоступно. Баланс не изменён.</p>
  }
  return <VkNativeCheckout packages={commerce.payment_packages}
    attempt={attempt} onAttemptChange={onAttemptChange} />
}
