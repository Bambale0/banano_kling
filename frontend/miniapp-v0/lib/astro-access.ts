/** Astro is an isolated, admin-only preview until its backend and billing exist. */
export const ASTRO_TAB_ID = 8

type AstroViewer = {
  mode: 'locked' | 'live'
  user: { isAdmin: boolean }
}

/** Trust the authenticated bootstrap role, never a browser flag or user-supplied id. */
export function isAstroVisible(viewer: AstroViewer): boolean {
  return viewer.mode === 'live' && viewer.user.isAdmin === true
}

/** Fails closed even if a stale tab id was restored or dispatched programmatically. */
export function effectiveTabId(tabId: number, viewer: AstroViewer): number {
  return tabId === ASTRO_TAB_ID && !isAstroVisible(viewer) ? 0 : tabId
}
