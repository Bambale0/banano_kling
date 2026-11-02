
import { personalizationError } from '@/lib/personalization-errors'
test.each([
  'HTTP 502 provider Nexus /v1/tasks?token=secret', 'Ошибка сервера: DATABASE_URL',
  'Не удалось обработать: {"token":"private"}', 'Traceback: /app/bot.py',
])('does not expose technical details: %s', message => {
  expect(personalizationError(new Error(message), 'Попробуйте ещё раз.')).toBe('Попробуйте ещё раз.')
})
test('keeps readable validation and upload constraints', () => {
  expect(personalizationError(new Error('Файл больше 20 MB.'), 'Ошибка')).toBe('Файл больше 20 MB.')
  expect(personalizationError(new Error('Сбой загрузки'), 'Ошибка')).toBe('Сбой загрузки')
})
