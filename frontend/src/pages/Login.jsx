import { useState } from 'react'
import { api, auth } from '../api.js'
import { Alert } from '../components/ui.jsx'

const FEATURES = [
  ['Practice interviews', 'Question a simulated subject while an AI assistant coaches every exchange.'],
  ['Blind scoring', 'Roles, tactics and scoring keys stay hidden until you lock a finding.'],
  ['Agent bake-off', 'Compare competing assistant and subject models under equal budgets.'],
]

export default function Login({ health, onLogin }) {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: localStorage.getItem('arena.investigator') || '', password: '', confirm: '' })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const switchMode = (m) => { setMode(m); setErr(null) }

  const submit = async (e) => {
    e.preventDefault(); setErr(null)
    if (mode === 'register' && form.password !== form.confirm) { setErr('The two passwords do not match.'); return }
    setBusy(true)
    try {
      const body = { username: form.username.trim(), password: form.password }
      const r = mode === 'login' ? await api.login(body) : await api.register(body)
      auth.set(r.token)
      onLogin(r.user)
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }

  const live = health && health.provider !== 'mock'
  return (
    <div className="login-shell">
      <section className="login-hero">
        <div>
          <div className="brand" style={{ padding: 0 }}>
            <img className="brand-mark" src="/favicon.svg" alt="" />
            <div><div className="brand-title">Investigative AI<br/>Training Arena</div><div className="brand-sub"><span className="wordmark">unissant</span> · Challenge X</div></div>
          </div>
          <h1>Practice the interview before it matters.</h1>
          <p className="lead">Investigators question simulated subjects while competing AI assistants coach them. Every case is synthetic, every finding is committed before the role is revealed, and every assistant must pass a false-accusation gate before it is ranked.</p>
          <ul className="login-features">
            {FEATURES.map(([t, d]) => <li key={t}><b>{t}</b><span>{d}</span></li>)}
          </ul>
        </div>
        <div className="login-runtime">
          <div className="row" style={{ gap: 8 }}>
            <span className="dot" style={{ background: !health ? 'var(--warn)' : live ? 'var(--good)' : 'var(--warn)' }} />
            <span>{!health ? 'Checking backend…' : live ? `Live agents · ${health.provider_label}` : 'Mock runtime · no model credentials configured'}</span>
          </div>
          {live && <div className="login-models">{health.assistant_models.map((m) => <span key={m} className="m">{m}</span>)}</div>}
          <div className="xs faint" style={{ marginTop: 10 }}>A simulated score is not a finding about a real person. A tournament rank is not certification for real investigations.</div>
        </div>
      </section>
      <section className="login-panel">
        <form onSubmit={submit} className="card login-card" aria-label={mode === 'login' ? 'Sign in' : 'Create account'}>
          <div className="card-body stack">
            <div className="seg login-seg">
              <button type="button" className={mode === 'login' ? 'on' : ''} onClick={() => switchMode('login')}>Sign in</button>
              <button type="button" className={mode === 'register' ? 'on' : ''} onClick={() => switchMode('register')}>Create account</button>
            </div>
            <div>
              <h2 style={{ fontSize: 18 }}>{mode === 'login' ? 'Welcome back' : 'New investigator'}</h2>
              <p className="small muted" style={{ marginTop: 4 }}>{mode === 'login' ? 'Sign in to continue your sessions and progress.' : 'Your username is the investigator name your sessions and progress are tracked under.'}</p>
            </div>
            <label className="field">Username
              <input required autoFocus autoComplete="username" value={form.username} onChange={set('username')} placeholder="e.g. j.rivera" maxLength={40} />
            </label>
            <label className="field">Password
              <input type="password" required minLength={6} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={form.password} onChange={set('password')} placeholder={mode === 'login' ? 'your password' : 'at least 6 characters'} />
            </label>
            {mode === 'register' && (
              <label className="field">Confirm password
                <input type="password" required minLength={6} autoComplete="new-password" value={form.confirm} onChange={set('confirm')} />
              </label>
            )}
            {err && <Alert tone="bad">{err}</Alert>}
            <button type="submit" className="btn" style={{ justifyContent: 'center' }} disabled={busy}>
              {busy ? <><span className="spinner" /> {mode === 'login' ? 'Signing in' : 'Creating account'}</> : mode === 'login' ? 'Sign in' : 'Create account and sign in'}
            </button>
            <p className="xs faint" style={{ margin: 0 }}>
              Demo trainer account: <span className="mono">trainer</span> / <span className="mono">arena-demo</span>. Change it with ARENA_ADMIN_USER and ARENA_ADMIN_PASSWORD in backend/.env.
            </p>
          </div>
        </form>
      </section>
    </div>
  )
}
