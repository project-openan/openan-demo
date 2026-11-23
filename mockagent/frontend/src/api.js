const TOKEN_KEY = 'openan-debug-token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

async function realFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(path, { ...options, headers })
  const text = await resp.text()
  let body = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = text
  }
  if (!resp.ok) {
    if (resp.status === 401 && getToken()) {
      setToken('')
      window.location.href = '/debug/'
    }
    const detail = body && body.detail ? (typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)) : `HTTP ${resp.status}`
    throw new ApiError(resp.status, detail)
  }
  return body
}

export async function apiFetch(path, options) {
  return realFetch(path, options)
}

export const api = {
  get: (path) => apiFetch(path),
  getText: async (path) => {
    const body = await apiFetch(path)
    return typeof body === 'string' ? body : String(body ?? '')
  },
  post: (path, json) => apiFetch(path, { method: 'POST', body: JSON.stringify(json) }),
  put: (path, json) => apiFetch(path, { method: 'PUT', body: JSON.stringify(json) }),
  patch: (path, json) => apiFetch(path, { method: 'PATCH', body: JSON.stringify(json) }),
  del: (path) => apiFetch(path, { method: 'DELETE' }),
}
