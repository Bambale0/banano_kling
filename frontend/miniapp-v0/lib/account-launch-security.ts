/** A magic-link launch may authenticate, but must never enter browser storage. */
export function containsAccountLink(raw: string): boolean {
  let decoded = raw
  for (let pass = 0; pass < 4; pass += 1) {
    if (/link_[A-Za-z0-9_-]{43}/.test(decoded)) return true
    try {
      const next = decodeURIComponent(decoded)
      if (next === decoded) break
      decoded = next
    } catch { break }
  }
  return false
}
