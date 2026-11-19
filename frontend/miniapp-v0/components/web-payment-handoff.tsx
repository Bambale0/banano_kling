'use client'

import { useEffect, useState } from 'react'

export function WebPaymentHandoff() {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const show = (event: Event) => setUrl((event as CustomEvent<string>).detail)
    window.addEventListener('neuromix-web-payment', show)
    return () => window.removeEventListener('neuromix-web-payment', show)
  }, [])
  if (!url) return null
  return (
    <aside role="status" aria-label="Оплата на сайте" className="fixed bottom-20 left-3 right-3 z-[110] mx-auto max-w-md rounded-2xl border border-gold/40 bg-background p-4 shadow-xl">
      <button type="button" aria-label="Закрыть ссылку на сайт" onClick={() => setUrl('')} className="float-right px-2 text-muted-foreground">×</button>
      <p className="text-sm text-foreground">Баланс и пополнение — на сайте NEUROMIX.</p>
      <a href={url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm font-semibold text-gold">Открыть сайт NEUROMIX</a>
    </aside>
  )
}
