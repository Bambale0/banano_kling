'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { currentAccountPlatform } from '@/lib/account-platform'
import { requestVkMessagePermission } from '@/lib/vk-message-permission'
import { fetchVkChatDelivery, requestVkChatDelivery, type VkChatDeliveryStatus } from '@/lib/shared-account-api'

const messages: Record<VkChatDeliveryStatus['state'], string> = {
  not_applicable: '',
  not_requested: 'Результат сохранён здесь. Его можно отправить в чат ВК.',
  pending: 'Отправляем в чат ВК…', preparing: 'Отправляем в чат ВК…', sending: 'Отправляем в чат ВК…',
  delivered: 'Отправлено в чат ВК.',
  permission_required: 'Разрешите сообщения сообщества в ВК, затем повторите отправку.',
  uncertain: 'ВК не подтвердил отправку. Проверьте чат. Результат доступен здесь.',
  failed: 'Не удалось отправить в чат ВК. Результат сохранён здесь.',
  access_revoked: 'Отправка в чат ВК сейчас недоступна. Результат сохранён здесь.',
  configuration_required: 'Отправка в чат ВК временно недоступна. Результат сохранён здесь.',
  disabled: 'Результат сохранён здесь. Отправка в чат ВК пока недоступна.',
}

export function VkChatDelivery({ taskId }: { taskId: string }) {
  const [visible, setVisible] = useState(false)
  const [delivery, setDelivery] = useState<VkChatDeliveryStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const alive = useRef(false)
  const operation = useRef<AbortController | null>(null)
  const deadline = useRef<ReturnType<typeof setTimeout> | null>(null)
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null)
  const polls = useRef(0)

  const run = useCallback(async function load(post = false) {
    operation.current?.abort()
    if (deadline.current) clearTimeout(deadline.current)
    if (poll.current) clearTimeout(poll.current)
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setError('')
    setHint('')
    const timer = setTimeout(() => {
      if (!alive.current || operation.current !== controller) return
      controller.abort()
      setBusy(false)
      setError(post ? 'Отправка не подтверждена. Обновите статус.' : 'Проверка заняла слишком много времени. Обновите статус.')
    }, 15000)
    deadline.current = timer
    try {
      const result = await (post ? requestVkChatDelivery : fetchVkChatDelivery)(taskId, controller.signal)
      if (!alive.current || controller.signal.aborted || operation.current !== controller) return
      setDelivery(result)
      if (['pending', 'preparing', 'sending'].includes(result.state) && polls.current++ < 20) {
        poll.current = setTimeout(() => { void load() }, 3000)
      }
    } catch (failure) {
      if (alive.current && !controller.signal.aborted && operation.current === controller) {
        setError(failure instanceof Error ? failure.message : 'Не удалось проверить доставку. Попробуйте ещё раз.')
      }
    } finally {
      clearTimeout(timer)
      if (alive.current && operation.current === controller) setBusy(false)
    }
  }, [taskId])

  useEffect(() => {
    if (currentAccountPlatform() !== 'vk') return
    alive.current = true
    polls.current = 0
    setVisible(true)
    setDelivery(null)
    void run()
    return () => {
      alive.current = false
      operation.current?.abort()
      if (deadline.current) clearTimeout(deadline.current)
      if (poll.current) clearTimeout(poll.current)
    }
  }, [run])

  if (!visible || delivery?.state === 'not_applicable') return null
  return <section aria-label="Доставка в чат ВК" className="space-y-2 rounded-xl border border-border/60 p-3 text-sm">
    <p role="status">{error && (!delivery || ['pending', 'preparing', 'sending'].includes(delivery.state))
      ? 'Результат доступен здесь.' : delivery?.state === 'delivered' && delivery.representation === 'link'
        ? 'Ссылка на результат отправлена в чат ВК.' : delivery ? messages[delivery.state] : 'Проверяем доставку в чат ВК…'}</p>
    {error ? <p role="alert" className="text-destructive">{error}</p> : null}
    {hint ? <p role="status">{hint}</p> : null}
    <div className="flex flex-wrap gap-2">
      {delivery?.community_id ? <Button asChild variant="outline" size="sm"><a
        href={`https://vk.com/write-${delivery.community_id}`} target="_blank" rel="noreferrer">Открыть чат ВК</a></Button> : null}
      {delivery?.state === 'permission_required' && delivery.community_id ? <Button type="button" size="sm" variant="outline"
        disabled={busy} onClick={() => setHint(requestVkMessagePermission(delivery.community_id!)
          ? 'Подтвердите разрешение в окне ВК, затем нажмите «Проверить и отправить».'
          : 'Откройте чат ВК и включите разрешение на сообщения сообщества, затем повторите отправку.')}>
        Разрешить сообщения ВК</Button> : null}
      {delivery?.can_request ? <Button type="button" size="sm" disabled={busy} onClick={() => {
        polls.current = 0
        void run(true)
      }}>{delivery.state === 'not_requested' ? 'Отправить в чат ВК' : 'Проверить и отправить'}</Button> : null}
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => {
        polls.current = 0
        void run()
      }}>Обновить статус</Button>
    </div>
  </section>
}
