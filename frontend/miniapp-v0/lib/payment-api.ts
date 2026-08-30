import type { CreatePaymentResponse, PaymentProvider } from './types'
import { getApiBasePath, getInitData, getStartParamFallback } from './api'

function paymentErrorMessage(value: unknown): string {
  if (typeof value === 'string') {
    const message = value.trim()
    if (message && message.toLowerCase() !== '[object object]') return message
    return ''
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const message = paymentErrorMessage(item)
      if (message) return message
    }
    return ''
  }

  if (value && typeof value === 'object') {
    const source = value as Record<string, unknown>
    for (const key of ['error', 'message', 'Message', 'detail', 'description', 'raw']) {
      const message = paymentErrorMessage(source[key])
      if (message) return message
    }
    for (const item of Object.values(source)) {
      const message = paymentErrorMessage(item)
      if (message) return message
    }
  }

  return ''
}

export async function createPayment(payload: {
  packageId: string
  provider: PaymentProvider
  promoCode?: string
  customerEmail?: string
}): Promise<CreatePaymentResponse> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await fetch(`${getApiBasePath()}/create-payment`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      package_id: payload.packageId,
      provider: payload.provider,
      promo_code: payload.promoCode || '',
      customer_email: payload.customerEmail?.trim() || '',
    }),
    cache: 'no-store',
    credentials: 'same-origin',
  })

  const text = await response.text()
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error('Платёжный сервис вернул некорректный ответ')
  }

  const statusPayload = data as { ok?: boolean; error?: unknown }
  if (!response.ok || statusPayload.ok === false) {
    throw new Error(paymentErrorMessage(statusPayload.error) || 'Не удалось создать платёж')
  }

  return data as CreatePaymentResponse
}
