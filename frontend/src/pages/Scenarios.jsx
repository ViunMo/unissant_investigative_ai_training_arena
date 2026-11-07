import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { Alert, Card, PageHeader, Pill, Spinner, Tabs } from '../components/ui.jsx'

function download(name, text, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const roleTone = (r) => (r === 'deceptive' ? 'warn' : 'good')

function ItemPreview({ it }) {
  const bad = it.errors.length > 0
  return (
    <div className="card subtle" style={{ padding: 12, borderColor: bad ? 'rgba(229,96,90,.5)' : undefined }}>
      <div className="row between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <div className="row" style={{ gap: 8 }}>
          <b className="mono">{it.case_id || `item ${it.index + 1}`}</b>
          {it.role && <Pill tone={roleTone(it.role)}>{it.role}</Pill>}
          {it.split && <Pill tone={it.split === 'hidden' ? 'warn' : 'muted'}>{it.split}</Pill>}
          {it.difficulty && <Pill tone="info">{it.difficulty}</Pill>}
          <Pill tone="muted">{it.kind === 'scenario' ? 'full scenario' : 'case brief'}</Pill>
        </div>
        <span className="xs muted">{it.title}{it.persona ? ` · subject ${it.persona}` : ''}</span>
      </div>
      {it.topics && (
        <div className="xs muted" style={{ marginTop: 6 }}>
          {it.topics.length} lines of questioning ({it.topics.map((t) => t.replace(/_/g, ' ')).join(', ')}) · {it.initial_documents} initial record(s) · {it.evidence_release} scripted release(s) · budget {it.max_turns}
        </div>
      )}
      {it.errors.length > 0 && <ul className="small" style={{ margin: '8px 0 0 18px', color: '#f6b3af' }}>{it.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {it.warnings.length > 0 && <ul className="small" style={{ margin: '8px 0 0 18px', color: '#f3cf7a' }}>{it.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
    </div>
  )
}

function Uploader({ onImported }) {
  const [tab, setTab] = useState('file')
  const [text, setText] = useState('')
  const [filename, setFilename] = useState('')
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState(null) // 'validate' | 'import' | 'draft' | 'template'
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [desc, setDesc] = useState('')
  const [roles, setRoles] = useState(['truthful', 'deceptive'])
  const [draftNote, setDraftNote] = useState(null)
  const fileRef = useRef()

  const readFile = (f) => {
    if (!f) return
    const r = new FileReader()
    r.onload = () => { setText(String(r.result)); setFilename(f.name); setResult(null); setError(null); setTab('edit') }
    r.readAsText(f)
  }
  const run = async (dry) => {
    setBusy(dry ? 'validate' : 'import'); setError(null)
    try {
      const r = await api.importScenarios({ content: text, filename: filename || null, dry_run: dry, replace })
      setResult(r)
      if (!dry && r.ok) onImported(r.imported)
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }
  const template = async (mode) => {
    setBusy('template'); setError(null)
    try {
      const t = await api.scenarioTemplate('yaml')
      if (mode === 'download') download('case-brief-template.yaml', t, 'application/yaml')
      else { setText(t); setFilename('case-brief-template.yaml'); setResult(null); setTab('edit') }
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }
  const draft = async () => {
    setBusy('draft'); setError(null); setDraftNote(null)
    try {
      const r = await api.draftScenarios({ description: desc, roles })
      setText(r.yaml); setFilename('drafted-cases.yaml'); setResult(null)
      setDraftNote({ n: r.cases.length, warnings: r.warnings })
      setTab('edit')
    } catch (e) { setError(e.message) } finally { setBusy(null) }
  }
  const toggleRole = (r) => setRoles((v) => (v.includes(r) ? v.filter((x) => x !== r) : [...v, r]))

  return (
    <Card title="Add cases" hint="bring a use-case provider's case in live" style={{ marginBottom: 16 }}
      right={<div className="row" style={{ gap: 6 }}>
        <button className="btn secondary sm" disabled={!!busy} onClick={() => template('download')}>Download template</button>
        <button className="btn secondary sm" disabled={!!busy} onClick={() => template('load')}>Open template in editor</button>
      </div>}>
      <div className="stack">
        <Tabs value={tab} onChange={setTab} items={[['file', 'Upload a file'], ['draft', 'Draft from a description'], ['edit', 'Review and import']]} />

        {tab === 'file' && (
          <div className="stack">
            <div className="small" style={{ color: 'var(--text-2)' }}>
              Drop a <b>case brief</b> (JSON or YAML, one case or a list) or a full scenario export. The template is a worked matched pair: copy it, change the story, keep the structure.
              Upload a truthful and a deceptive variant of the same case so the role can never be guessed from the story alone.
            </div>
            <div className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); readFile(e.dataTransfer.files[0]) }} onClick={() => fileRef.current?.click()}>
              <input ref={fileRef} type="file" accept=".json,.yaml,.yml,application/json" style={{ display: 'none' }} onChange={(e) => readFile(e.target.files[0])} />
              <div><b>Drop a .json / .yaml file here</b> or click to choose one</div>
              <div className="xs faint">Files are validated before anything is added. Nothing in the file is sent to a model.</div>
            </div>
          </div>
        )}

        {tab === 'draft' && (
          <div className="stack">
            <div className="small" style={{ color: 'var(--text-2)' }}>
              Paste the provider's incident description in plain language. The arena's coaching model drafts a matched pair in the brief format with fictional names; you review and edit it before importing. The draft goes to the hosted model, so do not paste real personal data.
            </div>
            <textarea rows={8} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. A night-shift pharmacist signed out 60 tablets of a controlled drug on 12 August against a prescription that was later voided. Stock counts were short by 60 the next morning. Policy requires a second signature for controlled-drug withdrawals…" />
            <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
              <div className="chips">
                {['truthful', 'deceptive'].map((r) => <button key={r} type="button" className={`chip ${roles.includes(r) ? 'on' : ''}`} onClick={() => toggleRole(r)}>{r} variant</button>)}
              </div>
              <button className="btn" disabled={busy || desc.trim().length < 20 || roles.length === 0} onClick={draft}>{busy === 'draft' ? <Spinner label="Drafting…" /> : 'Draft cases'}</button>
            </div>
          </div>
        )}

        {tab === 'edit' && (
          <div className="stack">
            <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
              <span className="small muted">{filename ? <>Editing <b className="mono">{filename}</b></> : 'Paste or edit case text below'}</span>
              <label className="row xs" style={{ gap: 6, cursor: 'pointer' }}><input type="checkbox" style={{ width: 'auto' }} checked={replace} onChange={(e) => setReplace(e.target.checked)} /> replace uploaded cases with the same id</label>
            </div>
            {draftNote && <Alert tone={draftNote.warnings.length ? 'warn' : 'good'}><div>Drafted {draftNote.n} case(s). {draftNote.warnings.length ? <>Review these before importing:<ul style={{ margin: '4px 0 0 18px' }}>{draftNote.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></> : 'No structural problems found; read the story through, then validate and import.'}</div></Alert>}
            <textarea className="mono" rows={18} value={text} onChange={(e) => { setText(e.target.value); setResult(null) }} placeholder="Paste a case brief or scenario JSON / YAML here, or open the template." spellCheck={false} style={{ fontSize: 12.5, lineHeight: 1.45 }} />
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <button className="btn secondary" disabled={!text.trim() || !!busy} onClick={() => run(true)}>{busy === 'validate' ? <Spinner label="Checking…" /> : 'Validate'}</button>
              <button className="btn" disabled={!text.trim() || !!busy || (result && !result.ok)} onClick={() => run(false)}>{busy === 'import' ? <Spinner label="Importing…" /> : 'Import into the arena'}</button>
              {text && <button className="btn ghost sm" onClick={() => download(filename || 'cases.yaml', text)}>Save a copy</button>}
            </div>
          </div>
        )}

        {error && <Alert tone="bad"><div>{error}</div></Alert>}
        {result && tab === 'edit' && (
          <div className="stack">
            <Alert tone={result.ok ? (result.dry_run ? 'info' : 'good') : 'bad'}>
              <div>
                {result.ok && !result.dry_run && <>Imported <b>{result.imported.join(', ')}</b>. The arena now has {result.cases} cases; they appear in Practice and Bake-off immediately.</>}
                {result.ok && result.dry_run && <>{result.items.length} case(s) parsed and compiled without errors. Nothing has been added yet; review the summary below, then import.</>}
                {!result.ok && <>The upload was not accepted: fix the errors below and validate again. Nothing was added.</>}
              </div>
            </Alert>
            <div className="stack" style={{ gap: 8 }}>{result.items.map((it) => <ItemPreview key={it.index} it={it} />)}</div>
          </div>
        )}
      </div>
    </Card>
  )
}

export default function Scenarios() {
  const [cases, setCases] = useState(null)
  const [me, setMe] = useState(null)
  const [note, setNote] = useState(null)
  const load = () => api.scenarios().then(setCases)
  useEffect(() => { load(); api.me().then(setMe).catch(() => {}) }, [])
  const trainer = me?.role === 'trainer'

  const remove = async (c) => {
    if (!window.confirm(`Remove ${c.case_id} (${c.title}) from the arena?`)) return
    try { await api.deleteScenario(c.case_id); setNote({ tone: 'good', text: `Removed ${c.case_id}.` }); load() } catch (e) { setNote({ tone: 'bad', text: e.message }) }
  }
  const exportCase = async (c) => {
    try { const b = await api.exportScenario(c.case_id, 'brief'); download(`${c.case_id}.json`, JSON.stringify(b, null, 2), 'application/json') } catch (e) { setNote({ tone: 'bad', text: e.message }) }
  }
  const uploaded = (cases || []).filter((c) => c.source === 'uploaded').length

  return (
    <>
      <PageHeader title="Case library" sub="Public packets only. Each family ships a matched truthful and deceptive variant at the same difficulty; which is which stays hidden until a finding is locked. Hidden-split cases are reserved for bake-offs."
        actions={cases && <span className="row" style={{ gap: 6 }}><Pill tone="muted">{cases.length} cases</Pill>{uploaded > 0 && <Pill tone="info">{uploaded} uploaded</Pill>}</span>} />
      {trainer && <Uploader onImported={(ids) => { setNote({ tone: 'good', text: `Added ${ids.join(', ')}.` }); load() }} />}
      {note && <div style={{ marginBottom: 12 }}><Alert tone={note.tone}><div className="row between" style={{ width: '100%' }}><span>{note.text}</span><button className="btn ghost sm" onClick={() => setNote(null)}>dismiss</button></div></Alert></div>}
      <div className="grid grid-2">
        {(cases || []).map((c) => (
          <Card key={c.case_id} title={c.title} hint={c.case_id} right={<span className="row" style={{ gap: 6 }}>{c.source === 'uploaded' && <Pill tone="info">uploaded</Pill>}<Pill tone="info">{c.difficulty}</Pill><Pill tone={c.split === 'hidden' ? 'warn' : 'muted'}>{c.split}</Pill></span>}>
            <div className="stack">
              <div><span className="muted">Objective.</span> {c.objective}</div>
              <div className="small" style={{ color: 'var(--text-2)' }}>{c.context}</div>
              <div>
                <h3 style={{ marginBottom: 6 }}>Known timeline</h3>
                <ul className="timeline">{c.known_timeline.map((t, i) => <li key={i}>{t}</li>)}</ul>
              </div>
              <div>
                <h3 style={{ marginBottom: 6 }}>Lines of questioning</h3>
                <div className="chips">{c.key_topics.map((t) => <span key={t} className="chip" style={{ cursor: 'default' }} title={c.question_bank[t]}>{t.replace(/_/g, ' ')}</span>)}</div>
              </div>
              <div className="row between" style={{ flexWrap: 'wrap', gap: 8 }}>
                <span className="xs muted">Initial record: {c.initial_documents.map((d) => d.title).join(', ')} · budget {c.max_turns} exchanges</span>
                <span className="row" style={{ gap: 6 }}>
                  {trainer && <button className="btn ghost sm" onClick={() => exportCase(c)} title="Download the full case (role and private packets included) as an editable brief">Export</button>}
                  {trainer && c.source === 'uploaded' && <button className="btn ghost sm" style={{ color: 'var(--bad)' }} onClick={() => remove(c)}>Remove</button>}
                  <Link className="btn secondary sm" to={`/practice?case=${c.case_id}`}>Practice this case</Link>
                </span>
              </div>
            </div>
          </Card>
        ))}
        {!cases && [1, 2, 3, 4].map((i) => <div key={i} className="card" style={{ height: 220, padding: 16 }}><div className="skeleton" style={{ width: '50%' }} /></div>)}
      </div>
    </>
  )
}
