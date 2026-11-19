import type { Metadata } from 'next'
import { LoginPanel } from '@/components/landing-login-panel'
import './login.css'

export const metadata: Metadata = {
  title: 'Войти в NEUROMIX — AI Creative Studio',
  description: 'Вход в веб-студию NEUROMIX через Telegram. Генерация фото, видео и работа с референсами.',
  robots: { index: false, follow: true },
}

export default function LoginPage() {
  return <LoginPanel />
}
