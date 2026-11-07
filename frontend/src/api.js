const TOKEN_KEY = 'arena.token'

export const auth = {
  token: () => localStorage.getItem(TOKEN_KEY),
  set: (token) => (token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)),
}

async function request(path, options = {}) {
  const token = auth.token()
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) },
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  if (res.status === 401 && !path.startsWith('/auth/')) {
    // expired or revoked token: drop it and let the app shell fall back to the login page
    auth.set(null)
    window.dispatchEvent(new Event('arena:unauthorized'))
  }
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  login: (body) => request('/auth/login', { method: 'POST', body }),
  register: (body) => request('/auth/register', { method: 'POST', body }),
  me: () => request('/auth/me'),
  scenarios: () => request('/scenarios'),
  candidates: (kind) => request(kind ? `/candidates?kind=${kind}` : '/candidates'),
  startSession: (body) => request('/sessions', { method: 'POST', body }),
  session: (id) => request(`/sessions/${id}`),
  sessions: (investigator) => request(investigator ? `/sessions?investigator=${encodeURIComponent(investigator)}` : '/sessions'),
  ask: (id, question) => request(`/sessions/${id}/ask`, { method: 'POST', body: { question } }),
  commit: (id, body) => request(`/sessions/${id}/finding`, { method: 'POST', body }),
  rate: (id, body) => request(`/sessions/${id}/trainer-rating`, { method: 'POST', body }),
  progress: (name) => request(`/investigators/${encodeURIComponent(name)}/progress`),
  startBakeoff: (body) => request('/bakeoffs', { method: 'POST', body }),
  bakeoffs: () => request('/bakeoffs'),
  bakeoff: (id) => request(`/bakeoffs/${id}`),
  stopBakeoff: (id) => request(`/bakeoffs/${id}/stop`, { method: 'POST' }),
  clearBakeoffs: () => request('/bakeoffs', { method: 'DELETE' }),
  deleteBakeoff: (id) => request(`/bakeoffs/${id}`, { method: 'DELETE' }),
  graphStatus: () => request('/graph/status'),
  graphInsights: () => request('/graph/insights'),
  graphSessions: (investigator) => request(investigator ? `/graph/sessions?investigator=${encodeURIComponent(investigator)}` : '/graph/sessions'),
  graphRebuild: () => request('/graph/rebuild', { method: 'POST' }),
}
