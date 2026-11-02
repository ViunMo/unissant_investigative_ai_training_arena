import { Pill, Quality, findingTone, findingLabel } from './ui.jsx'

export default function Coaching({ coaching, onUseFollowUp }) {
  if (!coaching) return <p className="muted small">Coaching is withheld in assessment mode and revealed in the debrief.</p>
  return (
    <div className="stack">
      <div className="row between">
        <span className="small muted">Question quality <Quality value={coaching.question_quality} /></span>
        <Pill tone={findingTone(coaching.interim_finding)}>{findingLabel(coaching.interim_finding)} · {(coaching.confidence * 100).toFixed(0)}%</Pill>
      </div>
      {coaching.question_feedback && <div className="small" style={{ color: 'var(--text-2)' }}>{coaching.question_feedback}</div>}
      {coaching.flags.length === 0
        ? <div className="small muted">No gaps or contradictions flagged on this exchange.</div>
        : coaching.flags.map((f, i) => (
          <div key={i} className={`flag ${f.kind}`}>
            <div className="kind"><span>{f.kind.replace('_', ' ')}</span><span>turn {f.turn_index}</span></div>
            <q>{f.evidence_quote}</q>
            <div className="muted small" style={{ marginTop: 3 }}>{f.issue}</div>
          </div>
        ))}
      {coaching.suggested_follow_up && (
        <div className="card subtle" style={{ padding: '10px 12px' }}>
          <div className="xs muted" style={{ marginBottom: 2 }}>Suggested neutral follow-up</div>
          <div>{coaching.suggested_follow_up}</div>
          {onUseFollowUp && <button className="btn ghost sm" style={{ marginTop: 4, marginLeft: -8 }} onClick={() => onUseFollowUp(coaching.suggested_follow_up)}>Use this question</button>}
        </div>
      )}
      {coaching.rationale && <div className="small muted">{coaching.rationale}</div>}
      <div className="xs faint">
        {coaching.latency_ms} ms{coaching.cost_usd ? ` · $${coaching.cost_usd.toFixed(4)}` : ''}{coaching.rubric_iterations > 1 ? ` · ${coaching.rubric_iterations} rubric iterations` : ''}
      </div>
    </div>
  )
}
