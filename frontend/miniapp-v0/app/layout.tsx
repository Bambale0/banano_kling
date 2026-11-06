import type { Metadata, Viewport } from 'next'
import { BRAND_DESCRIPTION, BRAND_NAME } from '@/lib/brand'
import { containsAccountLink } from '@/lib/account-launch-security'
import './globals.css'

const telegramBootstrapScript = `
(function () {
  var attempts = 0;
  var vkLaunch = ${JSON.stringify(process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk')} || new URLSearchParams(window.location.search).has('vk_app_id') || new URLSearchParams(window.location.search).has('vk_user_id');
  var containsAccountLink = ${containsAccountLink.toString()};

  function postVkInit() {
    // Keep the pre-hydration transport compatible with VK Bridge so the host
    // can dismiss its native loader before the React bundle starts.
    var handler = 'VKWebAppInit';
    var params = {};

    try {
      if (window.AndroidBridge && typeof window.AndroidBridge[handler] === 'function') {
        window.AndroidBridge[handler](JSON.stringify(params));
        return;
      }
    } catch (e) {}

    try {
      var iosHandler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers[handler];
      if (iosHandler && typeof iosHandler.postMessage === 'function') {
        iosHandler.postMessage(params);
        return;
      }
    } catch (e) {}

    try {
      if (window.ReactNativeWebView && typeof window.ReactNativeWebView.postMessage === 'function') {
        window.ReactNativeWebView.postMessage(JSON.stringify({ handler: handler, params: params }));
        return;
      }
    } catch (e) {}

    if (window.parent && typeof window.parent.postMessage === 'function') {
      try {
        window.parent.postMessage({
          handler: handler,
          params: params,
          type: 'vk-connect',
          connectVersion: '3.0.2'
        }, '*');
      } catch (e) {}
    }
  }

  try {
    window.__BANANO_INITIAL_LAUNCH__ = {
      hash: window.location.hash || '',
      search: window.location.search || ''
    };
    if (window.sessionStorage && !vkLaunch && !containsAccountLink(window.location.hash + window.location.search)) {
      window.sessionStorage.setItem('__banano_initial_hash', window.location.hash || '');
      window.sessionStorage.setItem('__banano_initial_search', window.location.search || '');
    } else if (window.sessionStorage) {
      window.sessionStorage.removeItem('__banano_initial_hash');
      window.sessionStorage.removeItem('__banano_initial_search');
      window.sessionStorage.removeItem('__banano_tg_init_data');
    }
  } catch (e) {}

  if (vkLaunch) {
    postVkInit();
    return;
  }

  function postTelegramEvent(eventType, eventData) {
    if (eventData === undefined) {
      eventData = '';
    }

    var eventDataJson = JSON.stringify(eventData);
    var payload = JSON.stringify({ eventType: eventType, eventData: eventData });

    if (window.TelegramWebviewProxy && typeof window.TelegramWebviewProxy.postEvent === 'function') {
      try {
        window.TelegramWebviewProxy.postEvent(eventType, eventDataJson);
      } catch (e) {}
    }

    if (
      window.webkit &&
      window.webkit.messageHandlers &&
      window.webkit.messageHandlers.TelegramWebviewProxy &&
      typeof window.webkit.messageHandlers.TelegramWebviewProxy.postMessage === 'function'
    ) {
      try {
        window.webkit.messageHandlers.TelegramWebviewProxy.postMessage(payload);
      } catch (e) {}
    }

    if (window.external && typeof window.external.notify === 'function') {
      try {
        window.external.notify(payload);
      } catch (e) {}
    }

    if (window.parent && window.parent !== window && typeof window.parent.postMessage === 'function') {
      try {
        window.parent.postMessage(payload, window.location.origin || '*');
      } catch (e) {}
    }
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

    if (attempts < 30) {
      window.setTimeout(markReady, 100);
    }
  }

  markReady();
  window.addEventListener('DOMContentLoaded', markReady, false);
  window.addEventListener('load', markReady, false);
})();
`

export const metadata: Metadata = {
  title: BRAND_NAME,
  description: BRAND_DESCRIPTION,
  applicationName: BRAND_NAME,
  generator: BRAND_NAME,
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
      <head>
        {process.env.NEXT_PUBLIC_MINIAPP_PLATFORM !== 'vk' && <script defer src={`${process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH?.replace(/\/$/, '') ?? '/mini-app'}/telegram-web-app.js`} />}
        <script
          id="telegram-early-ready"
          dangerouslySetInnerHTML={{ __html: telegramBootstrapScript }}
        />
      </head>
      <body className="font-sans antialiased">
        {children}
      </body>
    </html>
  )
}

