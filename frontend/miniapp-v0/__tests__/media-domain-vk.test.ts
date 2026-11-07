/**
 * @jest-environment-options {"url":"https://vk.neuromixbot.com/"}
 */
import { normalizeMiniAppMediaUrl } from '@/lib/media-url'

test.each([
  'https://neuromixbot.com/uploads/refs/image/public/example.png',
  'https://vk.neuromixbot.com/uploads/refs/image/public/example.png',
  'https://tanyapp.xn--e1aikcel5c5a.online/uploads/refs/image/public/example.png',
  '/uploads/refs/image/public/example.png',
])('VK serves first-party upload %s through its upload proxy', source => {
  expect(normalizeMiniAppMediaUrl(source)).toBe('https://vk.neuromixbot.com/uploads/refs/image/public/example.png')
})

test('external signed media keeps its original origin and signature on VK', () => {
  const source = 'https://provider.example/uploads/preview.png?signature=synthetic'
  expect(normalizeMiniAppMediaUrl(source)).toBe(source)
})
