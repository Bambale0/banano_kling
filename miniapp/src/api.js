const API_BASE = '/api/miniapp';

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const tg = window.Telegram?.WebApp;
  if (tg?.initData) headers['X-Telegram-Init-Data'] = tg.initData;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Ошибка запроса: ${response.status}`);
  return data;
}

export const api = {
  me: () => request('/me'),
  products: (includeInactive = false) => request(`/products${includeInactive ? '?include_inactive=1' : ''}`),
  settings: () => request('/settings'),
  updateSettings: (payload) => request('/settings', { method: 'PUT', body: payload }),
  createProduct: (payload) => request('/products', { method: 'POST', body: payload }),
  updateProduct: (id, payload) => request(`/products/${id}`, { method: 'PUT', body: payload }),
  deleteProduct: (id) => request(`/products/${id}`, { method: 'DELETE' }),
  uploadImage: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return request(`/products/${id}/images`, { method: 'POST', body: form });
  },
  createOrder: (payload) => request('/orders', { method: 'POST', body: payload }),
  orders: () => request('/orders'),
  generateContent: (payload) => request('/generate', { method: 'POST', body: payload }),
  smmPlan: (payload) => request('/generate/smm', { method: 'POST', body: payload }),
  goeBalance: () => request('/goe'),
  contentHistory: () => request('/history'),
};
