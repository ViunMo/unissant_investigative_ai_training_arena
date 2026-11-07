import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import KnowledgeGraph from '../components/KnowledgeGraph.jsx'
import { CONCEPT_GRAPH, LOOP_GRAPH, caseGraph, sessionGraph, flowFor } from '../graphs.js'
import { GROUP_COLORS } from '../components/KnowledgeGraph.jsx'
import { Card, PageHeader, Pill, Tabs, Tile, Empty } from '../components/ui.jsx'

const LOOPS = [
  ['L0', 'Validation loop', 'Every model call must return typed JSON. Parse, validate against the schema, re-prompt with the error, two retries, then degrade conservatively.'],
  ['L1', 'Rubric loop', 'deepagents RubricMiddleware: a grader model checks the coaching against a rubric (exact turn citations, no demeanor inference, neutral follow-up) and the assistant revises.'],
  ['L2', 'Interview loop', 'Question, subject answer, assistant assessment, scripted evidence release, budget check, finding committed and locked, independent scoring.'],
  ['L3', 'Bake-off loop', 'Freeze candidates, replay identical transcripts, cross-pair every assistant with every subject under equal budgets, score blind, gate, rank.'],
  ['L4', 'Investigator loop', 'Each locked session updates the questioning score; progress is measured against the investigator’s own first session, targeting +20%.'],
]

export default function Home({ health }) {
  const [tab, setTab] = useState('concepts')
  const [cases, setCases] = useState([])
  const [caseId, setCaseId] = useState('')
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState('')
  const [session, setSession] = useState(null)
  const [bakeoffs, setBakeoffs] = useState([])
  const [candidates, setCandidates] = useState([])
  const [selectedNode, setSelectedNode] = useState(null)
  useEffect(() => { setSelectedNode(null) }, [tab, caseId, sessionId])

  useEffect(() => {
    api.scenarios().then((c) => { setCases(c); setCaseId((id) => id || c[0]?.case_id || '') }).catch(() => {})
    api.sessions().then((s) => { const locked = s.filter((x) => x.status === 'locked'); setSessions(locked); setSessionId((id) => id || locked[0]?.id || '') }).catch(() => {})
    api.bakeoffs().then(setBakeoffs).catch(() => {})
    api.candidates().then(setCandidates).catch(() => {})
  }, [])
  useEffect(() => { if (sessionId) api.session(sessionId).then(setSession).catch(() => setSession(null)) }, [sessionId])

  const graph = useMemo(() => {
    if (tab === 'concepts') return CONCEPT_GRAPH
    if (tab === 'loops') return LOOP_GRAPH
    if (tab === 'case') { const c = cases.find((x) => x.case_id === caseId); return c ? caseGraph(c) : null }
    if (tab === 'session') return session ? sessionGraph(session) : null
    return null
  }, [tab, cases, caseId, session])

  const flow = useMemo(() => flowFor(tab, cases.find((x) => x.case_id === caseId), session), [tab, cases, caseId, session])
  const graphHeight = tab === 'concepts' ? 560 : 460
  const badges = useMemo(() => {
    const m = {}
    flow?.steps.forEach((st, i) => new Set(st.nodes || []).forEach((id) => { m[id] = m[id] || []; if (!m[id].includes(i + 1)) m[id].push(i + 1) }))
    Object.values(m).forEach((arr) => arr.sort((a, b) => a - b))
    return m
  }, [flow])

  const live = health && health.provider !== 'mock'
  const lockedCount = sessions.length
  const completed = bakeoffs.filter((b) => b.status === 'completed').length

  return (
    <>
      <PageHeader title="Overview" sub="Investigators practice interviews with simulated subjects while competing AI assistants coach them. Role labels and scoring keys stay hidden until a finding is locked; assistants must pass a false-accusation gate before they are ranked on detection."
        actions={<><Link className="btn" to="/practice">Start an interview</Link><Link className="btn secondary" to="/bakeoff">Run a bake-off</Link></>} />

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Tile k="Runtime" v={health ? (live ? (health.assistant_models?.length > 1 ? `${health.assistant_models.length} models` : health.assistant_model) : 'mock') : '…'} small tone={live ? 'good' : 'warn'}
          d={health ? (live ? `${health.assistant_models?.length > 1 ? health.assistant_models.join(' · ') + ' · ' : ''}LangChain deepagents · ${health.provider_label}` : 'no model credentials configured') : 'checking backend'} />
        <Tile k="Synthetic cases" v={cases.length || '…'} d={`${new Set(cases.map((c) => c.family_id)).size} families, matched truthful and deceptive variants`} />
        <Tile k="Candidates" v={candidates.length || '…'} d={`${candidates.filter((c) => c.kind === 'assistant').length} assistants · ${candidates.filter((c) => c.kind === 'subject').length} subjects`} />
        <Tile k="Locked sessions / bake-offs" v={`${lockedCount} / ${completed}`} d="debriefed interviews and completed tournaments" />
      </div>

      <Card title="Knowledge graphs" hint="how the arena's entities, loops, cases and evidence relate" style={{ marginBottom: 16 }}
        right={<span className="row" style={{ gap: 8 }}>
          {tab === 'case' && <select style={{ width: 'auto' }} value={caseId} onChange={(e) => setCaseId(e.target.value)}>{cases.map((c) => <option key={c.case_id} value={c.case_id}>{c.case_id} · {c.title}</option>)}</select>}
          {tab === 'session' && <select style={{ width: 'auto' }} value={sessionId} onChange={(e) => setSessionId(e.target.value)}>{sessions.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.case_id} · {s.investigator}</option>)}</select>}
        </span>}>
        <Tabs value={tab} onChange={setTab} items={[['concepts', 'Arena concepts'], ['loops', 'Loops and disciplines'], ['case', 'Case knowledge'], ['session', 'Session evidence']]} />
        <div className="kg-layout">
          <div>
            {graph
              ? <KnowledgeGraph key={tab + caseId + sessionId} nodes={graph.nodes} links={graph.links} height={graphHeight} selected={selectedNode} onSelect={setSelectedNode} badges={badges} />
              : <Empty title={tab === 'session' ? 'No locked session yet' : 'Loading'} hint={tab === 'session' ? 'Lock a finding on the Practice page to see its evidence graph here.' : undefined} />}
          </div>
          <aside className="flow" style={{ maxHeight: graphHeight + 40 }} aria-label="Flow description">
            {(() => {
              if (!flow) return <><h3>Flow</h3><p className="small muted">Select an item to see its flow.</p></>
              const selNode = selectedNode ? graph?.nodes.find((n) => n.id === selectedNode) : null
              const indexed = flow.steps.map((st, i) => ({ ...st, n: i + 1 }))
              const shown = selNode ? indexed.filter((st) => (st.nodes || []).includes(selNode.id)) : indexed
              return <>
                <div className="row between" style={{ marginBottom: 8 }}>
                  <h3 style={{ margin: 0 }}>{selNode ? 'Flow for selection' : 'Flow'}</h3>
                  {selNode && <button className="btn ghost sm" onClick={() => setSelectedNode(null)}>Show all {indexed.length} steps</button>}
                </div>
                {selNode
                  ? <p className="small" style={{ color: 'var(--text-2)', marginBottom: 10 }}>
                      <span className="pill muted" style={{ marginRight: 6 }}><i style={{ width: 8, height: 8, borderRadius: '50%', background: GROUP_COLORS[selNode.group], display: 'inline-block' }} />{selNode.label}</span>
                      {shown.length ? `appears in ${shown.length} of ${indexed.length} steps.` : 'is not part of a numbered step; it is context for the graph.'}
                      {selNode.title && selNode.title !== selNode.label && <span className="muted"> {selNode.title}</span>}
                    </p>
                  : <p className="small" style={{ color: 'var(--text-2)', marginBottom: 10 }}>{flow.intro} <span className="muted">Click a node to see only the steps it takes part in.</span></p>}
                <ol className="flow-steps">
                  {shown.map((st) => (
                    <li key={st.n}>
                      <span className="flow-n" style={{ borderColor: GROUP_COLORS[st.tone] || 'var(--border-strong)' }}>{st.n}</span>
                      <div><div className="flow-t">{st.title}</div>{st.lines ? st.lines.map((l, j) => <div key={j} className="flow-d">{l}</div>) : <div className="flow-d">{st.detail}</div>}</div>
                    </li>
                  ))}
                </ol>
              </>
            })()}
          </aside>
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>
          {tab === 'concepts' && 'Who sees what: the public packet reaches everyone, the private packet reaches only the subject, the evaluator packet reaches only the scorer and the scripted record releases.'}
          {tab === 'loops' && 'The five engineered loops nest inside each other; each discipline (prompt, context, harness, loop) points at the modules where it is applied.'}
          {tab === 'case' && 'Built from the public case packet only: objective, timeline, initial records and the lines of questioning. Nothing here reveals the role.'}
          {tab === 'session' && 'Turns in order, with the records released after each one, every flag pointing at the turn it cites, contradictions linked to the record they conflict with, and both locked findings against the revealed ground truth.'}
        </p>
      </Card>

      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <Card title="Loop engineering" hint="five nested loops, each with a budget, an exit and a measurement">
          <div className="stack">
            {LOOPS.map(([n, title, body]) => (
              <div key={n} className="row" style={{ alignItems: 'flex-start', gap: 12, flexWrap: 'nowrap' }}>
                <span className="rank" style={{ flex: 'none', fontSize: 11 }}>{n}</span>
                <div><b>{title}</b><div className="small muted">{body}</div></div>
              </div>
            ))}
          </div>
        </Card>
        <div className="stack">
          <Card title="Targets">
            <div className="table-wrap"><table>
              <tbody>
                <tr><td>Investigator questioning score</td><td className="num"><Pill tone="info">+20% vs own baseline</Pill></td></tr>
                <tr><td>Deceptive roles identified</td><td className="num"><Pill tone="info">at least 80%</Pill></td></tr>
                <tr><td>Truthful roles misclassified</td><td className="num"><Pill tone="bad">at most 5% · gate</Pill></td></tr>
                <tr><td>Subject profile fidelity</td><td className="num"><Pill tone="info">at least 95%</Pill></td></tr>
                <tr><td>Coaching latency</td><td className="num"><Pill tone="info">under 3 s for 95% of turns</Pill></td></tr>
              </tbody>
            </table></div>
          </Card>
          <Card title="Ground rules">
            <ul className="timeline">
              <li>All cases, people and records are synthetic.</li>
              <li>Nervousness, demeanor or accent are never evidence. Explicit uncertainty is not evasion.</li>
              <li>Evasive wording alone does not prove a violation. Prefer “not enough evidence” to an unsupported accusation.</li>
              <li>Assistants never see role labels, private profiles or scoring keys; every assistant input is scanned for private canaries.</li>
              <li>A tournament rank is not certification for real investigations.</li>
            </ul>
          </Card>
        </div>
      </div>

      <Card title="Quick start">
        <div className="grid grid-3">
          {[
            ['1', 'Practice an interview', 'Pick a case or let the arena choose one at random. Ask neutral, specific questions; the coaching panel flags gaps and suggests follow-ups.', '/practice', 'Open Practice'],
            ['2', 'Lock a finding and debrief', 'Commit truthful, deceptive or not enough evidence. The debrief reveals the facts, the subject’s tactics and your questioning score.', '/sessions', 'See progress'],
            ['3', 'Run a bake-off', 'Compare assistant and subject candidates on hidden cases. Only candidates that pass the false-positive and isolation gates are ranked.', '/bakeoff', 'Open Bake-off'],
          ].map(([n, t, b, to, cta]) => (
            <div key={n} className="card subtle" style={{ padding: 14 }}>
              <div className="row" style={{ gap: 10, marginBottom: 6 }}><span className="rank one">{n}</span><b>{t}</b></div>
              <div className="small muted" style={{ marginBottom: 10 }}>{b}</div>
              <Link className="btn secondary sm" to={to}>{cta}</Link>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
