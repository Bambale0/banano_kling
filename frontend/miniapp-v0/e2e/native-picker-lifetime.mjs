// Deterministic WebView regression: clearing the native picker invalidates
// its original handles while asynchronous FileReader work is still active.
export function expireClearedPickerFiles() {
  const expired = new WeakSet()
  const value = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
  Object.defineProperty(HTMLInputElement.prototype, 'value', {
    ...value,
    set(next) {
      if (this.type === 'file' && next === '') {
        for (const file of Array.from(this.files || [])) expired.add(file)
      }
      value.set.call(this, next)
    },
  })
  const read = FileReader.prototype.readAsDataURL
  FileReader.prototype.readAsDataURL = function (file) {
    const onload = this.onload
    this.onload = event => {
      if (expired.has(file)) this.onerror?.(new ProgressEvent('error'))
      else onload?.call(this, event)
    }
    return read.call(this, file)
  }
}
