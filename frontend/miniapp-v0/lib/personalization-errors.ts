/** Only short, readable validation messages may reach personalization screens. */
export function personalizationError(cause: unknown, fallback: string): string {
  if (!(cause instanceof Error)) return fallback
  const message = cause.message.trim()
  const plain = message.replace(/JPEG|PNG|WEBP|HEIC|GIF|MB/gi, '')
  if (!message || message.length > 240 || !/[А-Яа-яЁё]/.test(message)
    || /[A-Za-z]|[{}<>@\\/]/.test(plain)
    || /сервер|провайдер|рецепт|трассиров|внутренн.*ошибк|токен|стек/i.test(message)) return fallback
  return message
}
