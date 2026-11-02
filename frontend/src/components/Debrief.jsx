import { useState } from 'react'
import { api } from '../api.js'
import { Card, Pill, Tile, Alert, pct, findingLabel } from './ui.jsx'

const DIMS = [
  ['clarity_neutrality', 'Clarity and neutrality'],
  ['response_relevance', 'Response relevance'],
  ['evidence_based_follow_up', 'Evidence-based follow-up'],
  ['alternative_explanations', 'Testing alternative explanations'],
  ['supported_closure', 'Supported closure'],
]

export default function Debrief({ session, onUpdate }) {
  const d = session.debrief
  const [rating, setRating] = useState(Object.fromEntries(DIMS.map(([k]) => [k, session.trainer_rating?.[k] ?? 3])))
  const [err, setErr] = useState(null)
  const [saved, setSaved] = useState(!!session.trainer_rating)
  if (!d) return null
  const submit = async () => {
    try { onUpdate(await api.rate(session.id, rating)); setSaved(true); setErr(null) } catch (e) { setErr(e.message) }
  }
  const total = Object.values(rating).reduce((a, b) => a + b, 0) * 5
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className={`verdict ${d.investigator_correct ? 'good' : 'bad'}`}>
        <div>
          <div className="big">{d.investigator_correct ? 'Your finding matched the case facts' : 'Your finding did not match the case facts'}</div>
          <div className="small" style={{ color: 'var(--text-2)' }}>
            Ground truth: <b>{d.ground_truth_role}</b>{d.violation ? ` · ${d.violation}` : ' · no violation'}. You locked <b>{findingLabel(session.final_finding.finding)}</b> at {Math.round(session.final_finding.confidence * 100)}% confidence.
          </div>
        </div>
      </div>
      {d.notes.length > 0 && <Alert tone="warn"><div className="stack tight">{d.notes.map((n, i) => <div key={i}>{n}</div>)}</div></Alert>}
      <div className="grid grid-4">
        <Tile k="Questioning score (auto proxy)" v={d.investigator_auto_score} d="0 to 100 · five dimensions" />
        <Tile k="Assistant's locked finding" v={findingLabel(d.assistant_finding ?? 'n/a')} small tone={d.assistant_correct ? 'good' : 'bad'} d={d.assistant_correct ? 'correct' : 'incorrect'} />
        <Tile k="Topic coverage" v={pct(d.topic_coverage)} d="lines of questioning opened" />
        <Tile k="Evasion flags P / R" v={`${pct(d.evasion_precision)} / ${pct(d.evasion_recall)}`} small d={`${d.unsupported_flags} unsupported`} />
      </div>
      <div className="grid grid-2">
        <Card title="Case facts, now revealed">
          <ul className="timeline">{d.canonical_facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
          {d.material_contradictions.length > 0 && <>
            <h3 style={{ margin: '12px 0 6px' }}>Material contradictions</h3>
            <ul className="timeline">{d.material_contradictions.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </>}
          <h3 style={{ margin: '12px 0 6px' }}>Subject behaviour by turn</h3>
          <div className="chips">{d.tactic_by_turn.map((t, i) => <span key={i} className={`chip ${['truthful', 'uncertain'].includes(t) ? 'done' : 'on'}`} style={{ cursor: 'default' }}>{`T${i + 1} ${t}`}</span>)}</div>
          <div className="xs muted" style={{ marginTop: 10 }} >
            Subject fidelity {pct(d.subject_fidelity)} · isolation {d.isolation_pass ? <Pill tone="good">pass</Pill> : <Pill tone="bad">fail</Pill>} · mean coaching latency {d.coaching_mean_latency_ms} ms
          </div>
        </Card>
        <Card title="Trainer rubric" hint="blinded, 0 to 4 per dimension" right={saved && <Pill tone="good">saved</Pill>}>
          <div className="stack tight">
            {DIMS.map(([k, label]) => (
              <div key={k} className="row between">
                <span className="small">{label} <span className="faint">auto {d.questioning_dimensions[k]}</span></span>
                <select style={{ width: 70 }} value={rating[k]} onChange={(e) => { setRating({ ...rating, [k]: Number(e.target.value) }); setSaved(false) }}>
                  {[0, 1, 2, 3, 4].map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            ))}
            <div className="row between" style={{ marginTop: 6 }}>
              <span>Total <b>{total}</b> / 100</span>
              <button className="btn secondary sm" onClick={submit} disabled={saved}>Save rating</button>
            </div>
            {err && <Alert tone="bad">{err}</Alert>}
          </div>
        </Card>
      </div>
    </div>
  )
}
