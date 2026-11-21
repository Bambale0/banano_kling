'use client'

import { useEffect, useState } from 'react'
import { webReferralUrl } from '@/lib/web-public-links'

type Profile = { ok: true; code: string; display_name: string }

/** Public, deliberately minimal projection: no email, private tasks, money or session. */
export function WebPublicProfile({ code }: { code: string }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading')
    setProfile(null)
    void fetch('/mini-app/api/web-auth/public-profile?code=' + encodeURIComponent(code), {
      method: 'GET', cache: 'no-store', signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error('profile_unavailable')
      const data = await response.json() as Profile
      if (!data.ok || data.code !== code || typeof data.display_name !== 'string') {
        throw new Error('profile_unavailable')
      }
      if (!controller.signal.aborted) {
        setProfile(data)
        setStatus('ready')
      }
    }).catch(() => {
      if (!controller.signal.aborted) setStatus('unavailable')
    })
    return () => controller.abort()
  }, [code])

  const invite = webReferralUrl(code)
  return <main className="min-h-svh bg-[#111719] px-4 py-12 text-[#f2e8d5]">
    <section aria-label="Публичный профиль NEUROMIX"
      className="mx-auto max-w-xl space-y-6 border border-[#b38c55]/45 bg-[#1b2325] p-6 sm:p-10">
      <p className="text-xs font-bold uppercase tracking-[0.28em] text-[#eac184]">NEUROMIX / WEB</p>
      <h1 className="text-3xl font-black">Публичный профиль</h1>
      {status === 'loading' ? <p role="status">Открываем профиль…</p> : null}
      {status === 'unavailable' ? <p role="alert">Профиль не найден или временно недоступен.</p> : null}
      {status === 'ready' && profile ? <>
        <h2 className="break-words text-2xl font-semibold">{profile.display_name}</h2>
        <p className="text-sm text-[#bdb8ac]">Публичные публикации автора появятся здесь после их разрешённой публикации в веб-версии. Личные генерации и баланс закрыты.</p>
        <a href={invite} className="inline-flex min-h-11 items-center border border-[#d5ac73]/60 px-5 py-2 font-semibold text-[#f3ca86]">
          Присоединиться по приглашению
        </a>
      </> : null}
      <a href="/login?web=1" className="block pt-2 text-sm underline underline-offset-4">
        Открыть веб-студию NEUROMIX
      </a>
    </section>
  </main>
}
