'use client'

import { getApiBasePath } from '@/lib/api'

/** A VK actor must never be routed into Telegram Login Widget on bootstrap failure. */
export function VkLoginRecoveryGate() {
  return (
    <main className="relative flex min-h-svh items-center justify-center px-5 py-10" aria-label="Повторный вход ВКонтакте">
      <section className="w-full max-w-sm space-y-5 rounded-[28px] border border-white/10 bg-card/80 p-7 text-center shadow-2xl">
        <h1 className="text-2xl font-semibold tracking-wide">NEUROMIX</h1>
        <p className="text-sm text-muted-foreground">
          Не удалось открыть студию. Повторите вход через ВКонтакте.
          Telegram для входа не требуется.
        </p>
        <a
          href={`${getApiBasePath()}/account-preview/vk-login`}
          target="_top"
          rel="noreferrer"
          className="block w-full rounded-xl bg-primary px-4 py-3 text-center font-semibold text-primary-foreground"
        >
          Войти через ВКонтакте
        </a>
      </section>
    </main>
  )
}
