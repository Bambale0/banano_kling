import { clearPendingMotion, pendingMotionId } from '../motion-pending'

describe('Motion durable pending ownership', () => {
  beforeEach(() => localStorage.clear())
  const key = 'motion-pending:5000000001'
  const a = 'a'.repeat(32)
  const b = 'b'.repeat(32)

  test('reload restores the same original request identity', () => {
    localStorage.setItem(key, JSON.stringify({ requestId: a, payload: { requestId: a } }))
    expect(pendingMotionId(localStorage.getItem(key))).toBe(a)
    expect(clearPendingMotion(localStorage, key, a)).toBe(true)
    expect(localStorage.getItem(key)).toBeNull()
  })

  test('late success or rejection from unmounted A cannot delete newer B', () => {
    localStorage.setItem(key, JSON.stringify({ requestId: a }))
    expect(clearPendingMotion(localStorage, key, a)).toBe(true)
    localStorage.setItem(key, JSON.stringify({ requestId: b }))
    expect(clearPendingMotion(localStorage, key, a)).toBe(false)
    expect(pendingMotionId(localStorage.getItem(key))).toBe(b)
  })

  test('other actor key and malformed storage never claim the current operation', () => {
    localStorage.setItem(key, JSON.stringify({ requestId: a }))
    expect(clearPendingMotion(localStorage, 'motion-pending:202', a)).toBe(false)
    expect(pendingMotionId('{bad')).toBeNull()
    expect(pendingMotionId(JSON.stringify({ requestId: 'invalid' }))).toBeNull()
    expect(pendingMotionId(localStorage.getItem(key))).toBe(a)
  })
})
