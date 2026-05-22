import type { Metadata, Viewport } from 'next'
import { Analytics } from '@vercel/analytics/next'
import './globals.css'

const telegramBootstrapScript = `
(function () {
  var attempts = 0;

  function postTelegramEvent(eventType, eventData) {
    var payload = JSON.stringify({ eventType: eventType, eventData: eventData || {} });
    try {
      if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === 'function') {
        window.TelegramWebviewProxy.postEvent(eventType, JSON.stringify(eventData || {}));
      }
      if (window.external && typeof window.external.notify === 'function') {
        window.external.notify(payload);
      }
      if (window.parent && window.parent !== window && typeof window.parent.postMessage === 'function') {
        window.parent.postMessage(payload, '*');
      }
    } catch (e) {}
  }

  function markReady() {
    attempts += 1;
    var webApp = window.Telegram && window.Telegram.WebApp;

    if (webApp) {
      try { if (webApp.ready) webApp.ready(); } catch (e) {}
      try { if (webApp.expand) webApp.expand(); } catch (e) {}
    }

    postTelegramEvent('web_app_ready');
    postTelegramEvent('web_app_expand');

    if (attempts < 80) {
      window.setTimeout(markReady, 100);
    }
  }

  markReady();
  window.addEventListener('DOMContentLoaded', markReady, false);
  window.addEventListener('load', markReady, false);
})();
`

export const metadata: Metadata = {
  title: 'Banano AI Studio',
  description: 'Премиальная студия для генерации фото и видео с помощью AI',
  generator: 'v0.app',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: '#1a1a2e',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="ru" className="bg-background">
      <body className="font-sans antialiased">
        <script src="https://telegram.org/js/telegram-web-app.js" async />
        <script
          id="telegram-early-ready"
          dangerouslySetInnerHTML={{ __html: telegramBootstrapScript }}
        />
        {children}
        {process.env.NODE_ENV === 'production' && <Analytics />}
      </body>
    </html>
  )
}
