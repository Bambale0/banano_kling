'use client'

import { Button } from '@/components/ui/button'
import type { AccountPlatform } from '@/lib/account-platform'

function PlatformIcon({ platform }: { platform: AccountPlatform }) {
  return <span aria-hidden="true" className={`flex size-[42px] shrink-0 items-center justify-center rounded-[12px] text-white ${platform === 'telegram' ? 'bg-[#27a7e7]' : 'bg-[#0077ff]'}`}>
    {platform === 'telegram' ? <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="12" r="10" />
      <path d="m6.5 11.8 10.1-4c.5-.2.9.1.7.8l-1.7 8c-.1.6-.5.7-1 .4l-2.6-2-1.2 1.2c-.1.1-.3.2-.5.2l.2-2.7 5-4.5c.2-.2 0-.3-.2-.2l-6.2 3.9-2.5-.8c-.6-.2-.6-.5-.1-.7Z" fill="#27a7e7" />
    </svg> : <svg width="25" height="25" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 6h3.3c.3 0 .5.2.6.5.7 2.5 1.8 4.2 2.6 4.8.3.2.5.1.5-.4V7.6c0-.8-.4-1-1-1.1V6h4.5c.4 0 .5.2.5.6v5c0 .4.2.5.5.2 1.2-1.2 2.2-3 2.9-5.1.1-.4.3-.7.7-.7h3.1c.5 0 .6.3.4.8-.6 1.5-1.6 3.1-2.8 4.6-.3.4-.3.6 0 .9 1.2 1.1 2.3 2.3 3 3.5.3.6.1 1-.5 1h-3c-.5 0-.8-.3-1.2-.8-.8-1.1-1.6-1.9-2.3-2.4-.5-.3-.8-.1-.8.5v2c0 .5-.2.7-.9.7C7.5 18.8 4.4 13.3 2.5 6.8 2.4 6.3 2.6 6 3 6Z" />
    </svg>}
  </span>
}

export function LinkedAccountsCard({ linkedPlatforms, busy, failed, onLink, onRetry }: {
  linkedPlatforms: AccountPlatform[] | null
  busy: boolean
  failed: boolean
  onLink: (platform: AccountPlatform) => void
  onRetry: () => void
}) {
  return <section aria-label="Связанные аккаунты" className="rounded-[20px] border border-border bg-card px-[19px] pb-2 pt-[19px]">
    <h3 className="mb-3 text-[11px] font-normal uppercase tracking-[0.16em] text-muted-foreground">Связанные аккаунты</h3>
    <ul className="divide-y divide-border/50">
      {(['telegram', 'vk'] as const).map(platform => {
        const name = platform === 'telegram' ? 'Telegram' : 'ВКонтакте'
        const linked = linkedPlatforms?.includes(platform)
        return <li key={platform} className="flex min-h-[67px] items-center gap-3 py-3 min-[360px]:gap-3.5">
          <PlatformIcon platform={platform} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-6 text-foreground min-[360px]:text-base">{name}</p>
            <p className="text-[13px] leading-5 text-muted-foreground">{linkedPlatforms ? linked ? 'Привязан' : 'Не привязан' : failed ? 'Статус недоступен' : 'Проверяем…'}</p>
          </div>
          {linked ? <span aria-label={`${name} привязан`} className="flex size-8 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m6 12 4 4 8-10" /></svg>
          </span> : linkedPlatforms ? <Button variant="outline" aria-label={`Привязать ${name}`} disabled={busy} onClick={() => onLink(platform)} className="h-[42px] rounded-full border-border bg-foreground/[0.03] px-3 text-sm font-semibold min-[360px]:px-5">Привязать</Button> : null}
        </li>
      })}
    </ul>
    {failed ? <Button variant="ghost" onClick={onRetry} disabled={busy} className="mb-2 w-full">Повторить проверку</Button> : null}
  </section>
}
