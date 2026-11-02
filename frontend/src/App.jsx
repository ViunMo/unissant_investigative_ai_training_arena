import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api.js'
import Home from './pages/Home.jsx'
import Practice from './pages/Practice.jsx'
import Sessions from './pages/Sessions.jsx'
import Bakeoff from './pages/Bakeoff.jsx'
import Scenarios from './pages/Scenarios.jsx'

const I = {
  home: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>,
  chat: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 5h16v11H8l-4 4z"/></svg>,
  list: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 6h16M4 12h16M4 18h10"/></svg>,
  trophy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M8 4h8v5a4 4 0 0 1-8 0zM6 6H4a3 3 0 0 0 3 3M18 6h2a3 3 0 0 1-3 3M12 13v4m-4 3h8"/></svg>,
  folder: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/></svg>,
  book: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 4h7a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H5zM19 4h-4a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h5z"/></svg>,
}

const NAV = [
  ['/', 'Overview', I.home],
  ['/practice', 'Practice', I.chat],
  ['/sessions', 'Sessions', I.list],
  ['/bakeoff', 'Bake-off', I.trophy],
  ['/scenarios', 'Scenarios', I.folder],
]

export default function App() {
  const [health, setHealth] = useState(null)
  const [down, setDown] = useState(false)
  useEffect(() => {
    const load = () => api.health().then((h) => { setHealth(h); setDown(false) }).catch(() => setDown(true))
    load(); const t = setInterval(load, 15000); return () => clearInterval(t)
  }, [])
  const live = health && health.provider !== 'mock'
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">IA</div>
          <div><div className="brand-title">Investigative AI<br/>Training Arena</div></div>
        </div>
        <nav className="nav" aria-label="Main">
          <div className="section">Workspace</div>
          {NAV.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>{icon}{label}</NavLink>
          ))}
          <div className="section">Reference</div>
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">{I.book}API docs</a>
        </nav>
        <div className="sidebar-foot">
          <div className="runtime" title={health?.base_url || ''}>
            <div><span className="dot" style={{ background: down ? 'var(--bad)' : live ? 'var(--good)' : 'var(--warn)' }} />
              {down ? 'Backend unreachable' : live ? 'Live agents' : 'Mock runtime'}</div>
            {health && <div className="model">{live ? `${health.assistant_model} · ${health.provider === 'openai_compatible' ? 'gateway' : 'anthropic'}` : 'no model credentials'}</div>}
          </div>
          <div className="xs faint" style={{ padding: '0 4px' }}>All cases are synthetic. A simulated score is not a finding about a real person.</div>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Home health={health} />} />
          <Route path="/practice" element={<Practice />} />
          <Route path="/practice/:sessionId" element={<Practice />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/bakeoff" element={<Bakeoff />} />
          <Route path="/scenarios" element={<Scenarios />} />
        </Routes>
      </main>
    </div>
  )
}
