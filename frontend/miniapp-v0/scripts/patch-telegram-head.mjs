import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const outDir = join(process.cwd(), 'out')
const telegramSrc = 'https://telegram.org/js/telegram-web-app.js'
const telegramScript = `<script src="${telegramSrc}" async=""></script>`

const telegramEarlyScriptPattern =
  /<script\b(?=[^>]*\bid=(["'])telegram-early-ready\1)[^>]*>[\s\S]*?<\/script>/gi
const telegramSdkScriptPattern =
  /<script\b(?=[^>]*\bsrc=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js\1)[^>]*>\s*<\/script>/gi
const telegramSdkPreloadPattern =
  /<link\b(?=[^>]*\brel=(["'])preload\1)(?=[^>]*\bhref=(["'])https:\/\/telegram\.org\/js\/telegram-web-app\.js\2)[^>]*\/?>/gi
const scriptTagPattern = /<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/gi
const charsetPattern = /<head><meta\b[^>]*(?:charset|charSet)=(["'])utf-8\1[^>]*\/?>/i
const stylesheetPattern =
  /<link\b(?=[^>]*\brel=(["'])stylesheet\1)(?=[^>]*\bhref=(["'])(\/mini-app\/_next\/static\/css\/[^"']+\.css)\2)[^>]*\/?>/i

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((entry) => {
    const fullPath = join(dir, entry)
    const stat = statSync(fullPath)

    if (stat.isDirectory()) {
      return htmlFiles(fullPath)
    }

    return entry.endsWith('.html') ? [fullPath] : []
  })
}

function removeQueuedTelegramScripts(html) {
  return html.replace(scriptTagPattern, (tag) => {
    if (!tag.includes('self.__next_s')) {
      return tag
    }

    return tag.includes(telegramSrc) || tag.includes('telegram-early-ready') ? '' : tag
  })
}

function inlineMiniappStyles(html) {
  const stylesheetMatch = html.match(stylesheetPattern)
  const stylesheetTag = stylesheetMatch?.[0]
  const stylesheetHref = stylesheetMatch?.[3]

  if (!stylesheetTag || !stylesheetHref) {
    return html
  }

  const cssPath = join(outDir, stylesheetHref.replace(/^\/mini-app\//, ''))
  const css = readFileSync(cssPath, 'utf8').replace(/<\/style/gi, '<\\/style')
  const inlineStyle = `<style data-miniapp-inline-css="${stylesheetHref}">${css}</style>`

  if (html.includes(inlineStyle)) {
    return html
  }

  return html.replace(stylesheetTag, `${stylesheetTag}${inlineStyle}`)
}

let patched = 0

for (const file of htmlFiles(outDir)) {
  const html = readFileSync(file, 'utf8')
  telegramEarlyScriptPattern.lastIndex = 0

  const earlyScript = html.match(telegramEarlyScriptPattern)?.[0]

  if (!earlyScript) {
    throw new Error(`Cannot find telegram-early-ready script in ${file}`)
  }

  const stripped = removeQueuedTelegramScripts(
    html
      .replace(telegramSdkPreloadPattern, '')
      .replace(telegramSdkScriptPattern, '')
      .replace(telegramEarlyScriptPattern, ''),
  )

  if (!stripped.includes('<head>')) {
    throw new Error(`Cannot find <head> in ${file}`)
  }

  const telegramHeadScripts = `${telegramScript}${earlyScript}`
  const charsetMatch = stripped.match(charsetPattern)
  const nextHtmlWithTelegram = charsetMatch
    ? stripped.replace(charsetMatch[0], `${charsetMatch[0]}${telegramHeadScripts}`)
    : stripped.replace('<head>', `<head>${telegramHeadScripts}`)
  const nextHtml = inlineMiniappStyles(nextHtmlWithTelegram)

  if (nextHtml !== html) {
    writeFileSync(file, nextHtml)
    patched += 1
  }
}

console.log(`Patched Telegram head scripts in ${patched} HTML files.`)
