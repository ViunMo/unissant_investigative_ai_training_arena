import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Alert, Card, Empty, PageHeader, Pill, Tile, pct, fmtDate } from '../components/ui.jsx'

function Chips({ items, value, onChange, labelOf }) {
  const toggle = (id) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])
  return <div className="chips">{items.map((it) => <button type="button" key={it} className={`chip ${value.includes(it) ? 'on' : ''}`} onClick={() => toggle(it)}>{labelOf ? labelOf(it) : it}</button>)}</div>
}

function Matrix({ a }) {
  const cols = ['truthful', 'deceptive', 'insufficient_evidence']
  return (
    <table className="matrix">
      <thead><tr><th>truth \ output</th>{cols.map((c) => <th key={c}>{c.replace('_evidence', '')}</th>)}</tr></thead>
      <tbody>
        {['truthful', 'deceptive'].map((r) => (
          <tr key={r}><th>{r}</th>{cols.map((c) => <td key={c} className={a.matrix[r][c] ? (c === r ? 'hit' : c === 'insufficient_evidence' ? '' : 'miss') : ''}>{a.matrix[r][c]}</td>)}</tr>
        ))}
      </tbody>
    </table>
  )
}

const STATUS_TONE = { completed: 'good', failed: 'bad', cancelled: 'muted' }
const statusTone = (st) => STATUS_TONE[st] || 'warn'
const finished = (st) => ['completed', 'failed', 'cancelled'].includes(st)

const EVENT_TONE = { assistant_coached: 'accent', assistant_final: 'accent', subject_answered: 'info', evidence_released: 'warn', trial_done: 'good', phase: 'info' }

function EventRow({ e }) {
  const where = [e.track, e.case_id, e.turn ? `T${e.turn}` : null].filter(Boolean).join(' · ')
  const who = e.kind.startsWith('assistant') ? e.assistant_id : e.kind.startsWith('subject') ? e.subject_id : ''
  return (
    <div className="feed-row">
      <span className="xs faint mono">{new Date(e.ts).toLocaleTimeString()}</span>
      <Pill tone={EVENT_TONE[e.kind] || ''}>{e.kind.replace(/_/g, ' ')}</Pill>
      <div style={{ minWidth: 0 }}>
        <div className="small">{where && <span className="mono faint">{where} · </span>}{who && <span className="mono">{who} · </span>}{e.text}</div>
        {(e.model_input || e.model_output) && (
          <details>
            <summary className="xs muted" style={{ cursor: 'pointer' }}>{e.model_input ? 'data handed to the model' : 'model output'}{e.latency_ms ? ` · ${(e.latency_ms / 1000).toFixed(1)} s` : ''}</summary>
            <pre className="feed-pre">{e.model_input || e.model_output}</pre>
          </details>
        )}
      </div>
    </div>
  )
}

function LiveFeed({ run }) {
  const running = ['queued', 'running'].includes(run.status)
  const active = run.active?.length ? run.active : run.current ? [run.current] : []
  const events = [...(run.events || [])].reverse()
  const pctDone = run.total ? Math.round((100 * run.progress) / run.total) : 0
  return (
    <div className="stack" style={{ gap: 16 }}>
      {running && (
        <Card title={`Live · ${run.phase || 'starting'}`} hint="every model call as it happens; hidden labels stay hidden until each trial locks">
          <div className="stack tight">
            <div className="row between small muted">
              <span>{run.frozen_total ? `frozen transcripts ${run.frozen_transcripts} / ${run.frozen_total} · ` : ''}scored trials {run.progress} / {run.total}</span>
              <span>{pctDone}%</span>
            </div>
            <div className="progress"><div style={{ width: `${pctDone}%` }} /></div>
            {active.length ? active.map((cur, i) => (
              <div className="now" key={`${cur.track}-${cur.case_id}-${cur.assistant_id}-${cur.subject_id}-${cur.repeat}-${i}`}>
                <span><span className="faint">track</span> <b>{cur.track}</b></span>
                <span><span className="faint">case</span> <b className="mono">{cur.case_id}</b></span>
                {cur.assistant_id && <span><span className="faint">assistant</span> <b className="mono">{cur.assistant_id}</b></span>}
                <span><span className="faint">subject</span> <b className="mono">{cur.subject_id}</b></span>
                <span><span className="faint">exchange</span> <b>{cur.turn} / {cur.max_turns}</b></span>
                <span><span className="spinner" /> {cur.stage}</span>
              </div>
            )) : <div className="small muted"><span className="spinner" /> preparing the next trial</div>}
            <div className="xs muted">{run.workers > 1 ? `${run.workers} trials run at a time; ` : ''}identical model calls (replays, repeats, re-runs) are answered from the response cache; the feed below updates after every call.</div>
          </div>
        </Card>
      )}
      <Card title="Run log" hint={`${events.length} events · newest first · expand a row to see the exact text given to the model`} flush>
        {events.length === 0 ? <Empty title="No events yet" /> : <div className="feed">{events.map((e, i) => <EventRow key={`${e.ts}-${i}`} e={e} />)}</div>}
      </Card>
    </div>
  )
}

function Leaderboard({ run }) {
  const eligible = run.assistant_leaderboard.filter((a) => a.eligible)
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="grid grid-4">
        <Tile k="Trials" v={run.total} d={`${run.request.tracks.join(' + ')} · cap ${run.request.max_turns} exchanges`} />
        <Tile k="Role prevalence" v={`${run.role_prevalence.truthful} / ${run.role_prevalence.deceptive}`} d="truthful / deceptive trials" />
        <Tile k="Eligible assistants" v={`${eligible.length} / ${run.assistant_leaderboard.length}`} d="passed the 5% FP and isolation gates" />
        <Tile k="Winner" v={eligible[0]?.assistant_id ?? 'none'} small d={eligible[0] ? `recall ${pct(eligible[0].deceptive_recall)}` : 'no candidate passed the gates'} />
      </div>
      <Card title="Assistant leaderboard" hint="confidence intervals cluster-bootstrapped by case family" flush>
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th>Rank</th><th>Assistant</th><th className="num">Trials</th><th className="num">Deceptive recall</th><th className="num">False-positive rate</th><th className="num">PPV</th><th className="num">Unresolved T / D</th><th className="num">Evasion P / R</th><th className="num">Questioning</th><th className="num">Unsupported</th><th className="num">Latency mean / p95</th><th className="num">Cost</th><th>Status</th>
            </tr></thead>
            <tbody>
              {run.assistant_leaderboard.map((a) => (
                <tr key={a.assistant_id} className={a.eligible ? '' : 'ineligible'}>
                  <td>{a.rank ? <span className={`rank ${a.rank === 1 ? 'one' : ''}`}>{a.rank}</span> : <span className="faint">–</span>}</td>
                  <td className="mono">{a.assistant_id}</td>
                  <td className="num">{a.trials}</td>
                  <td className="num"><b>{pct(a.deceptive_recall)}</b> <span className="faint xs">[{pct(a.recall_ci95[0])}, {pct(a.recall_ci95[1])}]</span></td>
                  <td className="num"><Pill tone={a.false_positive_rate <= 0.05 ? 'good' : 'bad'}>{pct(a.false_positive_rate, 1)}</Pill></td>
                  <td className="num">{pct(a.ppv)}</td>
                  <td className="num">{pct(a.unresolved_rate_truthful)} / {pct(a.unresolved_rate_deceptive)}</td>
                  <td className="num">{pct(a.evasion_precision)} / {pct(a.evasion_recall)}</td>
                  <td className="num">{a.questioning_quality.toFixed(2)}</td>
                  <td className="num">{pct(a.unsupported_flag_rate)}</td>
                  <td className="num">{a.mean_latency_ms} / {a.p95_latency_ms} ms</td>
                  <td className="num">${a.total_cost_usd.toFixed(3)}</td>
                  <td>{a.eligible ? <Pill tone="good">eligible</Pill> : <Pill tone="bad" title={a.ineligible_reasons.join('; ')}>ineligible</Pill>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {run.assistant_leaderboard.some((a) => !a.eligible) && (
          <div style={{ padding: '10px 16px' }} className="stack tight">
            {run.assistant_leaderboard.filter((a) => !a.eligible).map((a) => <div key={a.assistant_id} className="small muted"><span className="mono">{a.assistant_id}</span>: {a.ineligible_reasons.join('; ')}</div>)}
          </div>
        )}
      </Card>
      <div className="grid grid-3">
        {run.assistant_leaderboard.map((a) => <Card key={a.assistant_id} title={a.assistant_id} hint="ground truth × output"><Matrix a={a} /></Card>)}
      </div>
      <Card title="Subject leaderboard" hint="truthful and deceptive runs scored separately" flush>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Subject</th><th className="num">Runs T / D</th><th className="num">Fidelity T / D</th><th className="num">Invalid sessions</th><th className="num">Deceptive success</th><th className="num">Truthful recognised</th><th className="num">Misleading clearance</th><th className="num">Unresolved</th></tr></thead>
            <tbody>
              {run.subject_leaderboard.map((s) => (
                <tr key={s.subject_id}>
                  <td className="mono">{s.subject_id}</td><td className="num">{s.truthful_runs} / {s.deceptive_runs}</td>
                  <td className="num"><Pill tone={Math.min(s.fidelity_truthful, s.fidelity_deceptive) >= 0.95 ? 'good' : 'warn'}>{pct(s.fidelity_truthful)} / {pct(s.fidelity_deceptive)}</Pill></td>
                  <td className="num">{s.invalid_sessions}</td><td className="num">{pct(s.deceptive_success_rate)}</td><td className="num">{pct(s.truthful_recognised_rate)}</td><td className="num">{pct(s.misleading_clearance_rate)}</td><td className="num">{pct(s.unresolved_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="xs muted">A tournament rank is not certification for real investigations. Eligibility requires a false-positive rate of at most 5% and a passing isolation check; eligible candidates rank by deceptive-role recall, then questioning quality.</p>
    </div>
  )
}

export default function Bakeoff() {
  const [assistants, setAssistants] = useState([])
  const [subjects, setSubjects] = useState([])
  const [cases, setCases] = useState([])
  const [runs, setRuns] = useState(null)
  const [selected, setSelected] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ assistant_ids: [], subject_ids: [], case_ids: [], repeats: 1, max_turns: 6, tracks: ['replay', 'interactive'], label: '' })

  useEffect(() => {
    // default: every model-backed assistant whose model can be called plus the evidence-first baseline,
    // against the first such subject
    const usable = (c) => c.runtime === 'deepagents' && c.available !== false
    api.candidates('assistant').then((a) => { setAssistants(a); setForm((f) => ({ ...f, assistant_ids: a.filter((c) => usable(c) || c.id === 'asst-mock-evidence-v1').map((c) => c.id) })) })
    api.candidates('subject').then((s) => { setSubjects(s); setForm((f) => ({ ...f, subject_ids: [(s.find(usable) || s[0])?.id].filter(Boolean) })) })
    api.scenarios().then(setCases)
    api.bakeoffs().then(setRuns)
  }, [])
  useEffect(() => {
    if (!selected || finished(selected.status)) return
    const t = setInterval(async () => {
      const r = await api.bakeoff(selected.id)
      setSelected(r)
      if (finished(r.status)) setRuns(await api.bakeoffs())
    }, 2000)
    return () => clearInterval(t)
  }, [selected?.id, selected?.status])

  const start = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      const r = await api.startBakeoff({ ...form, case_ids: form.case_ids.length ? form.case_ids : null, repeats: Number(form.repeats), max_turns: Number(form.max_turns) })
      setSelected(await api.bakeoff(r.id))
      setRuns(await api.bakeoffs())
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }
  const stopRun = async () => {
    if (!selected) return
    setErr(null)
    try { await api.stopBakeoff(selected.id); setSelected(await api.bakeoff(selected.id)) } catch (ex) { setErr(ex.message) }
  }
  const clearRuns = async () => {
    setErr(null)
    try {
      await api.clearBakeoffs()
      setRuns(await api.bakeoffs())
      if (selected && finished(selected.status)) setSelected(null)
    } catch (ex) { setErr(ex.message) }
  }
  const finishedRuns = (runs || []).filter((r) => finished(r.status)).length
  const labelOf = (list) => (id) => { const c = list.find((x) => x.id === id); return c ? `${c.label}${c.available === false ? ` · ${c.unavailable_reason || 'unavailable'}` : ''}` : id }
  const hidden = cases.filter((c) => c.split === 'hidden').length
  const trials = form.assistant_ids.length * form.subject_ids.length * (form.case_ids.length || hidden) * form.repeats * form.tracks.length

  return (
    <>
      <PageHeader title="Agent bake-off" sub="Freeze candidates, run the replay track on identical transcripts, then cross-pair assistants and subjects in live interviews under equal budgets. Findings are committed before labels are exposed; scoring is blind." />
      <form onSubmit={start} className="grid grid-2" style={{ marginBottom: 16, alignItems: 'start' }}>
        <Card title="Candidates">
          <div className="stack">
            <div><h3 style={{ marginBottom: 6 }}>Assistants</h3><Chips items={assistants.map((a) => a.id)} value={form.assistant_ids} onChange={(v) => setForm({ ...form, assistant_ids: v })} labelOf={labelOf(assistants)} /></div>
            <div><h3 style={{ marginBottom: 6 }}>Subjects</h3><Chips items={subjects.map((a) => a.id)} value={form.subject_ids} onChange={(v) => setForm({ ...form, subject_ids: v })} labelOf={labelOf(subjects)} /></div>
            <div><h3 style={{ marginBottom: 6 }}>Cases <span className="faint" style={{ textTransform: 'none', letterSpacing: 0 }}>· none selected = all {hidden} hidden-split cases</span></h3>
              <Chips items={cases.map((c) => c.case_id)} value={form.case_ids} onChange={(v) => setForm({ ...form, case_ids: v })} labelOf={(id) => { const c = cases.find((x) => x.case_id === id); return `${id}${c?.split === 'development' ? ' (dev)' : ''}` }} /></div>
          </div>
        </Card>
        <Card title="Run settings">
          <div className="stack">
            <div className="grid grid-3">
              <label className="field">Repeats<input type="number" min={1} max={5} value={form.repeats} onChange={(e) => setForm({ ...form, repeats: e.target.value })} /></label>
              <label className="field">Exchange cap<input type="number" min={2} max={20} value={form.max_turns} onChange={(e) => setForm({ ...form, max_turns: e.target.value })} /></label>
              <label className="field">Label<input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="optional" /></label>
            </div>
            <div><h3 style={{ marginBottom: 6 }}>Tracks</h3><Chips items={['replay', 'interactive']} value={form.tracks} onChange={(v) => setForm({ ...form, tracks: v })} /></div>
            <Alert tone="info"><div>≈ <b>{trials}</b> trials. Every exchange is two model calls (subject, then assistant); on hosted APIs that is a few seconds per exchange and trials run several at a time. Replays, repeats and re-runs reuse cached responses. For a smoke run pick one case and a low exchange cap. Mock baselines are instant.</div></Alert>
            {err && <Alert tone="bad">{err}</Alert>}
            <div><button type="submit" className="btn" disabled={busy || !form.assistant_ids.length || !form.subject_ids.length || !form.tracks.length}>{busy ? <><span className="spinner" /> Starting</> : 'Run bake-off'}</button></div>
          </div>
        </Card>
      </form>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(260px, 300px) minmax(0, 1fr)', alignItems: 'start' }}>
        <Card title="Runs" hint={runs ? `${runs.length}` : ''} flush right={<button type="button" className="btn ghost sm" onClick={clearRuns} disabled={!finishedRuns} title="Delete every finished run">Clear finished</button>}>
          <div className="stack tight" style={{ padding: 10 }}>
            {runs === null && [1, 2].map((i) => <div key={i} className="skeleton" />)}
            {runs && runs.length === 0 && <Empty title="No runs yet" />}
            {(runs || []).map((r) => (
              <button type="button" key={r.id} className="card subtle" style={{ textAlign: 'left', padding: 10, cursor: 'pointer', border: `1px solid ${selected?.id === r.id ? 'var(--accent)' : 'var(--border)'}`, color: 'inherit', font: 'inherit' }} onClick={async () => setSelected(await api.bakeoff(r.id))}>
                <div className="row between"><b className="small">{r.request.label || r.id}</b><Pill tone={statusTone(r.status)}>{r.status}</Pill></div>
                <div className="xs muted">{r.request.assistant_ids.length} assistants × {r.request.subject_ids.length} subjects · {r.request.tracks.join(' + ')} · {fmtDate(r.created_at)}</div>
                <div className="progress" style={{ marginTop: 6 }}><div style={{ width: `${r.total ? (100 * r.progress) / r.total : 0}%` }} /></div>
              </button>
            ))}
          </div>
        </Card>
        <div>
          {!selected && <Card><Empty title="Select a run to see its leaderboards" hint="or start a new one above" /></Card>}
          {selected && (
            <div className="stack" style={{ gap: 16 }}>
              <div className="row between">
                <div><h2>{selected.request.label || selected.id}</h2><div className="small muted">{selected.progress} / {selected.total} trials · started {fmtDate(selected.created_at)}</div></div>
                <div className="row" style={{ gap: 8 }}>
                  <Pill tone={statusTone(selected.status)}>{selected.status}</Pill>
                  {!finished(selected.status) && <button type="button" className="btn danger sm" onClick={stopRun}>Stop bake-off</button>}
                  {finished(selected.status) && <button type="button" className="btn ghost sm" onClick={async () => { await api.deleteBakeoff(selected.id); setSelected(null); setRuns(await api.bakeoffs()) }}>Delete</button>}
                </div>
              </div>
              {selected.status === 'cancelled' && <Alert tone="warn">Stopped by the user after {selected.progress} of {selected.total} trials. No leaderboard is produced for a partial run.</Alert>}
              {selected.status === 'failed' && <Alert tone="bad"><pre style={{ margin: 0, whiteSpace: 'pre-wrap', font: 'inherit' }}>{selected.error}</pre></Alert>}
              {selected.status === 'completed' && <Leaderboard run={selected} />}
              <LiveFeed run={selected} />
            </div>
          )}
        </div>
      </div>
    </>
  )
}
