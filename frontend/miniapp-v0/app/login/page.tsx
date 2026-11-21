import type { Metadata } from 'next'
import { LoginPanel } from '@/components/landing-login-panel'
import './login.css'

export const metadata: Metadata = {
  title: 'Войти в NEUROMIX — AI Creative Studio',
  description: 'NEUROMIX в браузере: вход через поддерживаемые Яндекс ID, Google, почту или Telegram. AI-генерация фото и видео.',
  robots: { index: false, follow: true },
}

export default function LoginPage() {
  return <LoginPanel />
}
