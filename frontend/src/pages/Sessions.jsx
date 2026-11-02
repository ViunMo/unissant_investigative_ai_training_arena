import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import ScoreChart from '../components/ScoreChart.jsx'
import { Card, Empty, PageHeader, Pill, Tile, fmtDate, findingLabel } from '../components/ui.jsx'

export default function Sessions() {
  const [name, setName] = useState(localStorage.getItem('arena.investigator') || '')
  const [sessions, setSessions] = useState(null)
  const [progress, setProgress] = useState(null)
  useEffect(() => {
    let alive = true
    Promise.all([api.sessions(name || undefined), name ? api.progress(name) : Promise.resolve(null)])
      .then(([s, p]) => { if (alive) { setSessions(s); setProgress(p) } }).catch(() => {})
    return () => { alive = false }
  }, [name])
  const imp = progress?.improvement_pct
  return (
    <>
      <PageHeader title="Sessions and progress" sub="Every locked session adds a point to the investigator's questioning score. Progress is measured against their own first session."
        actions={<label className="field" style={{ minWidth: 220 }}>Investigator<input value={name} onChange={(e) => { setName(e.target.value); localStorage.setItem('arena.investigator', e.target.value) }} placeholder="name" /></label>} />
      {progress && progress.sessions > 0 && (
        <div className="stack" style={{ gap: 16, marginBottom: 16 }}>
          <div className="grid grid-4">
            <Tile k="Locked sessions" v={progress.sessions} />
            <Tile k="Baseline score" v={progress.baseline ?? '–'} d="first locked session" />
            <Tile k="Recent average" v={progress.latest ?? '–'} d="up to three latest sessions" />
            <Tile k={`Improvement (target +${progress.target_pct}%)`} v={imp === null ? '–' : `${imp > 0 ? '+' : ''}${imp}%`} tone={imp === null ? undefined : imp >= progress.target_pct ? 'good' : imp >= 0 ? 'warn' : 'bad'} d={imp === null ? 'needs a second session' : imp >= progress.target_pct ? 'target met' : 'below target'} />
          </div>
          <Card title="Questioning score by session" hint="auto proxy, 0 to 100">
            <ScoreChart history={progress.history} baseline={progress.baseline} targetPct={progress.target_pct} />
          </Card>
        </div>
      )}
      <Card title="Session history" hint={name ? `investigator: ${name}` : 'all investigators'} flush>
        {sessions && sessions.length === 0 && <Empty title="No sessions yet" hint="Start one from the Practice page." />}
        {!sessions && <div style={{ padding: 16 }} className="stack tight">{[1, 2, 3].map((i) => <div key={i} className="skeleton" />)}</div>}
        {sessions && sessions.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Session</th><th>Case</th><th>Mode</th><th>Status</th><th>Finding</th><th className="num">Score</th><th className="num">Trainer</th><th>Created</th></tr></thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td><Link to={`/practice/${s.id}`} className="mono">{s.id}</Link></td>
                    <td>{s.case_id}</td>
                    <td>{s.mode}</td>
                    <td><Pill tone={s.status === 'locked' ? 'good' : 'warn'}>{s.status.replace('_', ' ')}</Pill></td>
                    <td>{s.debrief ? <Pill tone={s.debrief.investigator_correct ? 'good' : 'bad'}>{findingLabel(s.final_finding.finding)}</Pill> : <span className="faint">–</span>}</td>
                    <td className="num">{s.debrief?.investigator_auto_score ?? '–'}</td>
                    <td className="num">{s.trainer_rating ? Object.values(s.trainer_rating).reduce((a, b) => a + b, 0) * 5 : '–'}</td>
                    <td className="small muted">{fmtDate(s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
