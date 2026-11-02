import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import Coaching from '../components/Coaching.jsx'
import Debrief from '../components/Debrief.jsx'
import { Alert, Card, PageHeader, Pill, Quality, Spinner, Steps, findingLabel } from '../components/ui.jsx'

const STEPS = ['Set up', 'Interview', 'Lock finding', 'Debrief']

function StartForm({ onStart }) {
  const [params] = useSearchParams()
  const [cases, setCases] = useState([])
  const [assistants, setAssistants] = useState([])
  const [subjects, setSubjects] = useState([])
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    investigator: localStorage.getItem('arena.investigator') || '',
    mode: params.get('mode') === 'assessment' ? 'assessment' : 'practice',
    case_id: params.get('case') || '', assistant_id: 'asst-fast-v1', subject_id: 'subj-llm-v1', max_turns: 8,
  })
  const [err, setErr] = useState(null)
  useEffect(() => {
    api.scenarios().then(setCases)
    api.candidates('assistant').then(setAssistants)
    api.candidates('subject').then(setSubjects)
  }, [])
  const submit = async (e) => {
    e.preventDefault(); setErr(null); setBusy(true)
    try {
      localStorage.setItem('arena.investigator', form.investigator)
      onStart(await api.startSession({ ...form, case_id: form.case_id || null, max_turns: Number(form.max_turns) }))
    } catch (ex) { setErr(ex.message) } finally { setBusy(false) }
  }
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const asst = assistants.find((a) => a.id === form.assistant_id)
  return (
    <>
      <PageHeader title="Practice" sub="Set up an interview. In practice mode the assistant coaches after every exchange; in assessment mode its coaching is saved for the debrief." />
      <Steps steps={STEPS} current={0} />
      <form onSubmit={submit} className="grid grid-2" style={{ alignItems: 'start' }}>
        <Card title="Interview">
          <div className="stack">
            <label className="field">Investigator<input required value={form.investigator} onChange={set('investigator')} placeholder="your name" autoFocus /></label>
            <label className="field">Mode
              <div className="seg" style={{ alignSelf: 'flex-start' }}>
                <button type="button" className={form.mode === 'practice' ? 'on' : ''} onClick={() => setForm({ ...form, mode: 'practice' })}>Practice · live coaching</button>
                <button type="button" className={form.mode === 'assessment' ? 'on' : ''} onClick={() => setForm({ ...form, mode: 'assessment' })}>Assessment · coaching withheld</button>
              </div>
            </label>
            <label className="field">Case
              <select value={form.case_id} onChange={set('case_id')}>
                <option value="">Random case (role hidden)</option>
                {cases.map((c) => <option key={c.case_id} value={c.case_id}>{c.case_id} · {c.title} · {c.split}</option>)}
              </select>
              <span className="help">The role is hidden in every case. Random is closest to a real assessment.</span>
            </label>
            <label className="field">Exchange budget<input type="number" min={2} max={20} value={form.max_turns} onChange={set('max_turns')} style={{ width: 120 }} /><span className="help">Records are released after exchanges 2 and 4.</span></label>
          </div>
        </Card>
        <Card title="Agents">
          <div className="stack">
            <label className="field">Investigative assistant
              <select value={form.assistant_id} onChange={set('assistant_id')}>
                {assistants.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              </select>
              {asst && <span className="help">{asst.description || ''} Runtime: {asst.effective_runtime}.</span>}
            </label>
            <label className="field">Simulated subject
              <select value={form.subject_id} onChange={set('subject_id')}>
                {subjects.map((a) => <option key={a.id} value={a.id}>{a.label} · {a.effective_runtime}</option>)}
              </select>
            </label>
            {err && <Alert tone="bad">{err}</Alert>}
            <div className="row" style={{ marginTop: 4 }}>
              <button type="submit" className="btn" disabled={busy}>{busy ? <><span className="spinner" /> Starting</> : 'Begin interview'}</button>
            </div>
          </div>
        </Card>
      </form>
    </>
  )
}

export default function Practice() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [scenario, setScenario] = useState(null)
  const [question, setQuestion] = useState('')
  const [phase, setPhase] = useState(null) // 'subject' | 'assistant' | 'commit'
  const [err, setErr] = useState(null)
  const [finding, setFinding] = useState({ finding: 'insufficient_evidence', confidence: 0.5, rationale: '' })
  const [newest, setNewest] = useState([])
  const bottom = useRef(null)
  const input = useRef(null)

  useEffect(() => {
    if (sessionId) api.session(sessionId).then(setSession).catch((e) => setErr(e.message))
    else Promise.resolve().then(() => setSession(null))
  }, [sessionId])
  useEffect(() => {
    if (session) api.scenarios().then((cs) => setScenario(cs.find((c) => c.case_id === session.case_id)))
  }, [session?.case_id])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }, [session?.turns?.length, phase])

  const covered = useMemo(() => {
    if (!scenario || !session) return new Set()
    const s = new Set()
    session.turns.forEach((t) => { const q = t.question.toLowerCase(); Object.entries(scenario.topic_keywords).forEach(([topic, kws]) => { if (kws.some((k) => q.includes(k))) s.add(topic) }) })
    return s
  }, [scenario, session])

  if (!session) return <StartForm onStart={(s) => navigate(`/practice/${s.id}`)} />

  const locked = session.status === 'locked'
  const active = session.status === 'active'
  const step = locked ? 3 : active ? 1 : 2
  const lastCoaching = session.turns.length ? session.turns[session.turns.length - 1].coaching : null
  const used = session.turns.length

  const ask = async (e) => {
    e?.preventDefault()
    if (!question.trim() || phase) return
    setErr(null); setPhase('subject')
    const t = setTimeout(() => setPhase('assistant'), 2500)
    try {
      const r = await api.ask(session.id, question)
      setNewest(r.turn.evidence_released.map((x) => x.id))
      setSession(await api.session(session.id))
      setQuestion('')
      setTimeout(() => input.current?.focus(), 0)
    } catch (ex) { setErr(ex.message) } finally { clearTimeout(t); setPhase(null) }
  }
  const commit = async (e) => {
    e.preventDefault(); setErr(null); setPhase('commit')
    try { setSession(await api.commit(session.id, { ...finding, confidence: Number(finding.confidence) })); window.scrollTo({ top: 0, behavior: 'smooth' }) }
    catch (ex) { setErr(ex.message) } finally { setPhase(null) }
  }

  return (
    <>
      <PageHeader crumbs={`Practice / ${session.id}`} title={scenario?.title ?? session.case_id}
        sub={scenario ? scenario.objective : ''}
        actions={<>
          <Pill tone="info">{session.mode}</Pill>
          <Pill tone={locked ? 'good' : active ? 'muted' : 'warn'}>{session.status.replace('_', ' ')}</Pill>
          <button className="btn secondary sm" onClick={() => navigate('/practice')}>New interview</button>
        </>} />
      <Steps steps={STEPS} current={step} />

      {locked && <Card title="Debrief" style={{ marginBottom: 16 }}><Debrief session={session} onUpdate={setSession} /></Card>}

      <div className="split">
        <div className="stack" style={{ gap: 16 }}>
          <Card title="Interview" hint={`${used} of ${session.max_turns} exchanges`} right={<div className="progress accent" style={{ width: 140 }}><div style={{ width: `${(100 * used) / session.max_turns}%` }} /></div>}>
            {scenario && used === 0 && (
              <Alert tone="info"><div><b>Context.</b> {scenario.context} <span className="muted">Suggested opening: “{scenario.initial_question}”</span></div></Alert>
            )}
            <div className="transcript" style={{ marginTop: used === 0 ? 12 : 0 }}>
              {session.turns.map((t) => (
                <div key={t.index} className="stack tight">
                  <div className="msg q">
                    <div className="bubble"><div className="who">You · T{t.index} {t.coaching && <Quality value={t.coaching.question_quality} />}</div>{t.question}</div>
                    <div className="avatar i">You</div>
                  </div>
                  <div className="msg a">
                    <div className="avatar s">S</div>
                    <div className="bubble"><div className="who">Subject{locked && <Pill tone={['truthful', 'uncertain'].includes(t.tactic) ? 'good' : 'warn'}>{t.tactic}</Pill>}</div>{t.answer}</div>
                  </div>
                  {t.evidence_released.map((e) => (
                    <div key={e.id} className={`record ${newest.includes(e.id) ? 'new' : ''}`} style={{ marginLeft: 40 }}>
                      <div className="title"><span>New record released: {e.title}</span><span className="mono muted">{e.id}</span></div>
                      <div style={{ color: 'var(--text-2)' }}>{e.content}</div>
                    </div>
                  ))}
                </div>
              ))}
              {phase === 'subject' && <Spinner label="Subject is answering…" />}
              {phase === 'assistant' && <Spinner label="Assistant is reviewing the exchange…" />}
              <div ref={bottom} />
            </div>
            {active && (
              <form onSubmit={ask} className="composer">
                <input ref={input} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a neutral, specific question and press Enter" disabled={!!phase} autoFocus />
                <button type="submit" className="btn" disabled={!!phase || !question.trim()}>Ask</button>
              </form>
            )}
            {!active && !locked && <Alert tone="warn">Exchange budget used. Lock a finding below to see the debrief.</Alert>}
            {err && <div style={{ marginTop: 10 }}><Alert tone="bad">{err}</Alert></div>}
          </Card>

          {!locked && used > 0 && (
            <Card title="Lock a finding" hint="committed before the role is revealed">
              <form onSubmit={commit} className="stack">
                <div className="seg" style={{ alignSelf: 'flex-start' }}>
                  {[['truthful', 'Truthful', 'good'], ['deceptive', 'Deceptive', 'bad'], ['insufficient_evidence', 'Not enough evidence', 'warn']].map(([v, l, tone]) => (
                    <button key={v} type="button" className={finding.finding === v ? `on ${tone}` : ''} onClick={() => setFinding({ ...finding, finding: v })}>{l}</button>
                  ))}
                </div>
                <div className="grid grid-2">
                  <label className="field">Confidence · {Math.round(finding.confidence * 100)}%
                    <input type="range" min={0} max={1} step={0.05} value={finding.confidence} onChange={(e) => setFinding({ ...finding, confidence: e.target.value })} />
                  </label>
                </div>
                <label className="field">Rationale <span className="help">cite turn numbers and record ids</span>
                  <textarea value={finding.rationale} onChange={(e) => setFinding({ ...finding, rationale: e.target.value })} placeholder="e.g. T3 claims Priya authorized entry; A-E2 shows she was off shift and the subject did not reconcile it." />
                </label>
                <div className="row between">
                  <span className="small muted">Choose “not enough evidence” over an unsupported accusation. A false accusation scores zero on closure.</span>
                  <button type="submit" className="btn" disabled={!!phase}>{phase === 'commit' ? <><span className="spinner" /> Scoring</> : `Lock “${findingLabel(finding.finding)}” and debrief`}</button>
                </div>
              </form>
            </Card>
          )}
        </div>

        <div className="stack sticky" style={{ gap: 16 }}>
          <Card title="Assistant coaching" hint={lastCoaching ? `turn ${used}` : ''}>
            {used === 0 ? <p className="muted small">Coaching appears after each exchange.</p>
              : <Coaching coaching={lastCoaching} onUseFollowUp={active ? (q) => { setQuestion(q); input.current?.focus() } : null} />}
          </Card>
          <Card title="Released records" hint={`${session.released_evidence.length}`}>
            <div className="stack tight">
              {session.released_evidence.map((e) => (
                <div key={e.id} className="record"><div className="title"><span>{e.title}</span><span className="mono muted">{e.id}</span></div><div style={{ color: 'var(--text-2)' }}>{e.content}</div></div>
              ))}
            </div>
          </Card>
          {scenario && (
            <Card title="Lines of questioning" hint={`${covered.size} of ${scenario.key_topics.length} opened`}>
              <div className="chips">
                {scenario.key_topics.map((t) => (
                  <button key={t} type="button" className={`chip ${covered.has(t) ? 'done' : ''}`} disabled={!active} title={scenario.question_bank[t]} onClick={() => { setQuestion(scenario.question_bank[t]); input.current?.focus() }}>{covered.has(t) ? '✓ ' : ''}{t.replace('_', ' ')}</button>
                ))}
              </div>
              <h3 style={{ margin: '14px 0 6px' }}>Known timeline</h3>
              <ul className="timeline">{scenario.known_timeline.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
