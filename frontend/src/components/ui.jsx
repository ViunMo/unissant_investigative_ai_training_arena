export function Pill({ tone = 'muted', children, title }) {
  return <span className={`pill ${tone}`} title={title}>{children}</span>
}

export function Quality({ value }) {
  return (
    <span className="quality" title={`Question quality ${value} of 4`} aria-label={`Question quality ${value} of 4`}>
      {[1, 2, 3, 4].map((i) => <i key={i} className={i <= value ? 'on' : ''} />)}
    </span>
  )
}

export function Tile({ k, v, d, tone, small }) {
  return (
    <div className="tile">
      <span className="k">{k}</span>
      <span className={`v ${small ? 'sm' : ''}`} style={tone ? { color: `var(--${tone})` } : undefined}>{v}</span>
      {d && <span className="d">{d}</span>}
    </div>
  )
}

export function PageHeader({ title, sub, actions, crumbs }) {
  return (
    <div className="page-head">
      <div>
        {crumbs && <div className="crumbs">{crumbs}</div>}
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  )
}

export function Card({ title, hint, right, children, className = '', flush = false, style }) {
  return (
    <section className={`card ${className}`} style={style}>
      {(title || right) && (
        <div className="card-head">
          <div className="row" style={{ gap: 8 }}><h2>{title}</h2>{hint && <span className="hint">{hint}</span>}</div>
          {right}
        </div>
      )}
      <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  )
}

export function Alert({ tone = 'info', children }) {
  return <div className={`alert ${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>{children}</div>
}

export function Empty({ icon = '·', title, hint }) {
  return <div className="empty"><div className="icon">{icon}</div><div>{title}</div>{hint && <div className="small faint">{hint}</div>}</div>
}

export function Spinner({ label }) {
  return <span className="thinking"><span className="spinner" />{label}</span>
}

export function Steps({ steps, current }) {
  return (
    <div className="steps" aria-label="Progress">
      {steps.map((s, i) => (
        <span key={s} style={{ display: 'contents' }}>
          <span className={`step ${i === current ? 'on' : i < current ? 'done' : ''}`}><span className="n">{i < current ? '✓' : i + 1}</span>{s}</span>
          {i < steps.length - 1 && <span className="step-sep" />}
        </span>
      ))}
    </div>
  )
}

export function Tabs({ items, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {items.map(([id, label]) => <button key={id} role="tab" aria-selected={value === id} className={value === id ? 'on' : ''} onClick={() => onChange(id)}>{label}</button>)}
    </div>
  )
}

export function pct(x, digits = 0) {
  if (x === null || x === undefined) return 'n/a'
  return `${(x * 100).toFixed(digits)}%`
}

export function findingTone(f) {
  return f === 'deceptive' ? 'bad' : f === 'truthful' ? 'good' : 'warn'
}

export function findingLabel(f) {
  return f === 'insufficient_evidence' ? 'not enough evidence' : f
}

export function fmtDate(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const AVATAR_LABEL = { investigator: 'Investigator (you)', subject: 'Simulated subject', assistant: 'Investigative assistant' }
const AVATAR_ICON = {
  investigator: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l7 3v5c0 4.8-3 8.4-7 10-4-1.6-7-5.2-7-10V6z"/><path d="M9.3 12.2l1.9 1.9 3.6-4"/></svg>,
  subject: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5c.6-4 3.6-6.3 7.5-6.3s6.9 2.3 7.5 6.3"/></svg>,
  assistant: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="8" width="16" height="11" rx="3.5"/><path d="M12 4v4M9 13.5h.01M15 13.5h.01M9.5 16.5h5"/></svg>,
}

/** Profile mark for a conversation participant: investigator (shield), subject (person) or assistant (robot). */
export function Avatar({ who, size = 30 }) {
  return <span className={`avatar ${who}`} style={{ width: size, height: size }} role="img" aria-label={AVATAR_LABEL[who]} title={AVATAR_LABEL[who]}>{AVATAR_ICON[who]}</span>
}

/** Chat-style "someone is typing" row: avatar plus three bouncing dots. */
export function Typing({ who, label }) {
  return (
    <div className="msg a typing-row" role="status" aria-live="polite" aria-label={label}>
      <Avatar who={who} />
      <div className="bubble typing-bubble">
        <div className="who">{label}</div>
        <span className="typing" aria-hidden="true"><i /><i /><i /></span>
      </div>
    </div>
  )
}
