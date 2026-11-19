import type { Metadata } from 'next'
import { LoginPanel } from '@/components/landing-login-panel'
import './login.css'

export const metadata: Metadata = {
  title: 'Войти в NEUROMIX — AI Creative Studio',
  description: 'Вход в NEUROMIX через Яндекс ID или Telegram. Управление аккаунтом и доступ к AI-студии.',
  robots: { index: false, follow: true },
}

export default function LoginPage() {
  return <LoginPanel />
}
