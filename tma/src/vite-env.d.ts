/// <reference types="vite/client" />

interface TelegramWebAppUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
  photo_url?: string
  language_code?: string
}

interface TelegramWebApp {
  initData?: string
  initDataUnsafe?: {
    user?: TelegramWebAppUser
  }
  colorScheme?: 'light' | 'dark'
  ready: () => void
  expand: () => void
  close: () => void
  sendData: (data: string) => void
  openTelegramLink?: (url: string) => void
  HapticFeedback?: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void
    selectionChanged: () => void
  }
}

interface Window {
  Telegram?: {
    WebApp?: TelegramWebApp
  }
}
