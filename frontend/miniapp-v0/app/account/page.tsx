import type { Metadata } from 'next'
import { WebAccountWorkspace } from '@/components/web-account-workspace'

export const metadata: Metadata = {
  title: 'Мой аккаунт NEUROMIX',
  description: 'Управление способами входа и связкой аккаунтов NEUROMIX.',
  robots: { index: false, follow: false },
}

export default function AccountPage() {
  return <WebAccountWorkspace />
}
