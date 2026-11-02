import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { Card, PageHeader, Pill } from '../components/ui.jsx'

export default function Scenarios() {
  const [cases, setCases] = useState(null)
  useEffect(() => { api.scenarios().then(setCases) }, [])
  return (
    <>
      <PageHeader title="Case library" sub="Public packets only. Each family ships a matched truthful and deceptive variant at the same difficulty; which is which stays hidden until a finding is locked. Hidden-split cases are reserved for bake-offs." />
      <div className="grid grid-2">
        {(cases || []).map((c) => (
          <Card key={c.case_id} title={c.title} hint={c.case_id} right={<span className="row" style={{ gap: 6 }}><Pill tone="info">{c.difficulty}</Pill><Pill tone={c.split === 'hidden' ? 'warn' : 'muted'}>{c.split}</Pill></span>}>
            <div className="stack">
              <div><span className="muted">Objective.</span> {c.objective}</div>
              <div className="small" style={{ color: 'var(--text-2)' }}>{c.context}</div>
              <div>
                <h3 style={{ marginBottom: 6 }}>Known timeline</h3>
                <ul className="timeline">{c.known_timeline.map((t, i) => <li key={i}>{t}</li>)}</ul>
              </div>
              <div>
                <h3 style={{ marginBottom: 6 }}>Lines of questioning</h3>
                <div className="chips">{c.key_topics.map((t) => <span key={t} className="chip" style={{ cursor: 'default' }} title={c.question_bank[t]}>{t.replace('_', ' ')}</span>)}</div>
              </div>
              <div className="row between">
                <span className="xs muted">Initial record: {c.initial_documents.map((d) => d.title).join(', ')} · budget {c.max_turns} exchanges</span>
                <Link className="btn secondary sm" to={`/practice?case=${c.case_id}`}>Practice this case</Link>
              </div>
            </div>
          </Card>
        ))}
        {!cases && [1, 2, 3, 4].map((i) => <div key={i} className="card" style={{ height: 220, padding: 16 }}><div className="skeleton" style={{ width: '50%' }} /></div>)}
      </div>
    </>
  )
}
