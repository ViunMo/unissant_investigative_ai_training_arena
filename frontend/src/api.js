async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
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
}
