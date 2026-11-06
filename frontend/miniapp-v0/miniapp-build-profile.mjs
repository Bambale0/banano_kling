// Undefined retains the existing Telegram prefix; an explicit root is valid.
const configuredPath = process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH
export const miniAppBasePath = configuredPath === undefined
  ? '/mini-app'
  : configuredPath === '/' ? '' : configuredPath.replace(/\/$/, '')
export const vkBuild = process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk'
