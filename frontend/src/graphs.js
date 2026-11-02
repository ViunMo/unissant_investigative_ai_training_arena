/** Graph datasets for the Overview page. Static ones describe the arena; the others are built from API data. */

export const CONCEPT_GRAPH = {
  nodes: [
    { id: 'investigator', label: 'Investigator', group: 'actor', size: 18 },
    { id: 'trainer', label: 'Trainer', group: 'actor' },
    { id: 'assistant', label: 'Investigative assistant', group: 'agent', size: 18 },
    { id: 'subject', label: 'Simulated subject', group: 'agent', size: 18 },
    { id: 'harness', label: 'Fixed interviewer harness', group: 'agent' },
    { id: 'scenario', label: 'Scenario', group: 'scenario', size: 16 },
    { id: 'public', label: 'Public packet', group: 'scenario' },
    { id: 'private', label: 'Private subject packet', group: 'scenario' },
    { id: 'evaluator', label: 'Evaluator packet', group: 'scenario' },
    { id: 'records', label: 'Released records', group: 'evidence' },
    { id: 'transcript', label: 'Transcript', group: 'evidence' },
    { id: 'flags', label: 'Flags (cite turns)', group: 'evidence' },
    { id: 'followup', label: 'Neutral follow-up', group: 'evidence' },
    { id: 'finding', label: 'Locked finding', group: 'scoring', size: 16 },
    { id: 'scorer', label: 'Independent scorer', group: 'scoring', size: 16 },
    { id: 'debrief', label: 'Debrief', group: 'scoring' },
    { id: 'isolation', label: 'Isolation check', group: 'control' },
    { id: 'fpgate', label: 'False-positive gate 5%', group: 'control' },
    { id: 'leaderboard', label: 'Leaderboards', group: 'scoring' },
    { id: 'bakeoff', label: 'Bake-off', group: 'scoring' },
  ],
  links: [
    { source: 'investigator', target: 'subject', label: 'interviews' },
    { source: 'assistant', target: 'investigator', label: 'coaches' },
    { source: 'harness', target: 'subject', label: 'interviews in bake-offs' },
    { source: 'scenario', target: 'public' }, { source: 'scenario', target: 'private' }, { source: 'scenario', target: 'evaluator' },
    { source: 'public', target: 'assistant', label: 'visible' }, { source: 'public', target: 'investigator', label: 'visible' },
    { source: 'private', target: 'subject', label: 'role, persona, scripts' },
    { source: 'evaluator', target: 'records', label: 'scripted release' },
    { source: 'records', target: 'assistant' }, { source: 'records', target: 'investigator' },
    { source: 'subject', target: 'transcript', label: 'answers' }, { source: 'transcript', target: 'assistant' },
    { source: 'assistant', target: 'flags', label: 'produces' }, { source: 'assistant', target: 'followup', label: 'suggests' },
    { source: 'flags', target: 'transcript', label: 'quote exact turn' },
    { source: 'investigator', target: 'finding', label: 'commits' }, { source: 'assistant', target: 'finding', label: 'commits own' },
    { source: 'finding', target: 'scorer' }, { source: 'evaluator', target: 'scorer', label: 'hidden facts' },
    { source: 'private', target: 'scorer', label: 'tactic labels', dashed: true },
    { source: 'scorer', target: 'debrief' }, { source: 'debrief', target: 'trainer', label: 'blinded rubric' },
    { source: 'scorer', target: 'isolation' }, { source: 'scorer', target: 'fpgate' },
    { source: 'bakeoff', target: 'harness' }, { source: 'bakeoff', target: 'scorer' },
    { source: 'isolation', target: 'leaderboard', label: 'gate' }, { source: 'fpgate', target: 'leaderboard', label: 'gate' },
  ],
}

export const LOOP_GRAPH = {
  nodes: [
    { id: 'L0', label: 'L0 validation loop', group: 'loop', size: 16, title: 'parse, validate, re-prompt with the error' },
    { id: 'L1', label: 'L1 rubric loop', group: 'loop', size: 16, title: 'grader model grades against a rubric; agent revises' },
    { id: 'L2', label: 'L2 interview loop', group: 'loop', size: 18, title: 'question, answer, assessment, evidence release, budget, lock' },
    { id: 'L3', label: 'L3 bake-off loop', group: 'loop', size: 18, title: 'frozen transcripts, replay, interactive, blind scoring, gates' },
    { id: 'L4', label: 'L4 investigator loop', group: 'loop', size: 16, title: 'progress vs own baseline, +20% target' },
    { id: 'agentloop', label: 'Agent loop (deepagents)', group: 'loop', title: 'act, observe, act again with lookup tools' },
    { id: 'prompt', label: 'Prompt engineering', group: 'discipline' },
    { id: 'context', label: 'Context engineering', group: 'discipline' },
    { id: 'harnessd', label: 'Harness engineering', group: 'discipline' },
    { id: 'loopd', label: 'Loop engineering', group: 'discipline', size: 16 },
    { id: 'prompts', label: 'prompts.py', group: 'module' },
    { id: 'ctx', label: 'context.py', group: 'module' },
    { id: 'llm', label: 'llm.py', group: 'module' },
    { id: 'profiles', label: 'profiles.py', group: 'module' },
    { id: 'val', label: 'validation_loop.py', group: 'module' },
    { id: 'il', label: 'interview_loop.py', group: 'module' },
    { id: 'bl', label: 'bakeoff_loop.py', group: 'module' },
    { id: 'sc', label: 'scoring.py', group: 'module' },
    { id: 'cand', label: 'candidates.py', group: 'module' },
  ],
  links: [
    { source: 'L4', target: 'L3', label: 'contains' }, { source: 'L3', target: 'L2', label: 'contains' },
    { source: 'L2', target: 'L1', label: 'contains' }, { source: 'L1', target: 'L0', label: 'contains' },
    { source: 'L0', target: 'agentloop', label: 'wraps' },
    { source: 'loopd', target: 'L0' }, { source: 'loopd', target: 'L1' }, { source: 'loopd', target: 'L2' }, { source: 'loopd', target: 'L3' }, { source: 'loopd', target: 'L4' },
    { source: 'prompt', target: 'prompts' }, { source: 'prompt', target: 'L1', label: 'rubrics' },
    { source: 'context', target: 'ctx' }, { source: 'context', target: 'L2', label: 'evidence timing' },
    { source: 'harnessd', target: 'profiles' }, { source: 'harnessd', target: 'llm' }, { source: 'harnessd', target: 'cand' }, { source: 'harnessd', target: 'agentloop', label: 'tool set' },
    { source: 'L0', target: 'val' }, { source: 'L1', target: 'llm' }, { source: 'L2', target: 'il' }, { source: 'L3', target: 'bl' }, { source: 'L3', target: 'sc' }, { source: 'L4', target: 'sc' },
  ],
}

/** Public case packet -> graph. Never includes role, tactics or evaluator data. */
export function caseGraph(c) {
  const nodes = [{ id: 'case', label: c.title, group: 'scenario', size: 20, title: c.objective }]
  const links = []
  nodes.push({ id: 'objective', label: 'Objective', group: 'scoring', title: c.objective })
  links.push({ source: 'case', target: 'objective' })
  c.known_timeline.forEach((t, i) => {
    nodes.push({ id: `tl${i}`, label: t.length > 34 ? t.slice(0, 32) + '…' : t, group: 'timeline', size: 10, title: t })
    links.push({ source: i === 0 ? 'case' : `tl${i - 1}`, target: `tl${i}`, label: i === 0 ? 'timeline' : undefined, distance: 70 })
  })
  c.initial_documents.forEach((d) => {
    nodes.push({ id: d.id, label: `${d.title} (${d.id})`, group: 'evidence', title: d.content })
    links.push({ source: 'case', target: d.id, label: 'initial record' })
  })
  c.key_topics.forEach((t) => {
    nodes.push({ id: `t_${t}`, label: t.replace('_', ' '), group: 'topic', size: 13, title: c.question_bank[t] })
    links.push({ source: 'case', target: `t_${t}`, label: 'line of questioning' })
  })
  return { nodes, links }
}

/** Locked session -> evidence graph: turns, flags citing turns, records, contradictions, findings. */
export function sessionGraph(s) {
  const nodes = [{ id: 'case', label: s.case_id, group: 'scenario', size: 18 }]
  const links = []
  s.turns.forEach((t, i) => {
    const id = `T${t.index}`
    nodes.push({ id, label: `${id}${t.tactic ? ` · ${t.tactic}` : ''}`, group: 'turn', size: 13, title: `Q: ${t.question}\nA: ${t.answer}` })
    links.push({ source: i === 0 ? 'case' : `T${s.turns[i - 1].index}`, target: id, distance: 60 })
    t.evidence_released.forEach((e) => {
      nodes.push({ id: e.id, label: `${e.title} (${e.id})`, group: 'evidence', title: e.content })
      links.push({ source: id, target: e.id, label: 'released after' })
    })
    ;(t.coaching?.flags || []).forEach((f, j) => {
      const fid = `f${t.index}_${j}`
      const contradiction = f.kind === 'contradiction'
      nodes.push({ id: fid, label: f.kind.replace('_', ' '), group: contradiction ? 'contradiction' : 'flag', size: 9, title: `${f.issue}\n“${f.evidence_quote}”` })
      links.push({ source: fid, target: `T${f.turn_index}`, label: 'cites', color: contradiction ? '#d55181' : undefined })
      if (contradiction) {
        const text = `${f.issue} ${f.evidence_quote}`.toLowerCase()
        const rec = s.released_evidence.find((e) => text.includes(e.id.toLowerCase()) || text.includes(e.title.toLowerCase()))
        if (rec) links.push({ source: fid, target: rec.id, label: 'conflicts with', color: '#d55181', dashed: true })
      }
    })
  })
  s.released_evidence.forEach((e) => { if (!nodes.some((n) => n.id === e.id)) { nodes.push({ id: e.id, label: `${e.title} (${e.id})`, group: 'evidence', title: e.content }); links.push({ source: 'case', target: e.id, label: 'initial record' }) } })
  if (s.final_finding) {
    nodes.push({ id: 'inv', label: `Investigator: ${s.final_finding.finding.replace('_', ' ')}`, group: 'finding', size: 14 })
    links.push({ source: `T${s.turns[s.turns.length - 1].index}`, target: 'inv', label: 'locked' })
  }
  if (s.assistant_final) {
    nodes.push({ id: 'asst', label: `Assistant: ${s.assistant_final.finding.replace('_', ' ')}`, group: 'finding', size: 14, title: s.assistant_final.rationale })
    links.push({ source: `T${s.turns[s.turns.length - 1].index}`, target: 'asst', label: 'locked' })
  }
  if (s.debrief) {
    nodes.push({ id: 'truth', label: `Ground truth: ${s.debrief.ground_truth_role}`, group: s.debrief.ground_truth_role === 'deceptive' ? 'contradiction' : 'evidence', size: 14, title: s.debrief.violation || 'no violation' })
    links.push({ source: 'inv', target: 'truth', label: s.debrief.investigator_correct ? 'correct' : 'wrong' })
    if (s.assistant_final) links.push({ source: 'asst', target: 'truth', label: s.debrief.assistant_correct ? 'correct' : 'wrong' })
  }
  return { nodes, links }
}

/** Flow narration shown next to each graph. Returns { intro, steps: [{ title, detail | lines, tone? }] }. */
export function flowFor(tab, c, s) {
  if (tab === 'concepts') {
    return {
      intro: 'How one interview moves through the arena, and who is allowed to see what at each step.',
      steps: [
        { nodes: ['scenario', 'public', 'private', 'evaluator'], title: 'Scenario engine locks a case', detail: 'A deep copy of the scenario is split into three packets: public, private subject, evaluator-only. Nothing a trial does can change the ground truth.' },
        { nodes: ['investigator', 'harness', 'public', 'records', 'transcript'], title: 'Investigator asks a question', detail: 'The investigator (or the fixed harness in a bake-off) sees only the public packet and the records released so far.' },
        { nodes: ['subject', 'private', 'transcript'], title: 'Simulated subject answers', detail: 'The subject plays its private packet: role, persona, communication style, permitted tactics. It reports a hidden tactic for the turn.' },
        { nodes: ['assistant', 'public', 'transcript', 'records', 'flags', 'followup'], title: 'Assistant assesses the exchange', detail: 'From the public packet, the transcript and released records only. It flags gaps and contradictions citing exact turns, rates the question, and suggests a neutral follow-up.' },
        { nodes: ['evaluator', 'records'], title: 'Evaluator packet releases a record', detail: 'Scripted releases arrive after fixed exchanges. The assistant assessed this turn with the records released before it, so replays match live runs.' },
        { nodes: ['finding', 'investigator', 'assistant'], title: 'Findings are locked', detail: 'The investigator commits truthful, deceptive or not enough evidence. The assistant commits its own finding from the full transcript. Both happen before any label is revealed.' },
        { nodes: ['scorer', 'finding', 'evaluator', 'private', 'isolation'], title: 'Independent scorer grades', detail: 'Findings are compared with the hidden facts; flags with the subject’s tactic labels; every assistant input is scanned for private canaries (isolation check).' },
        { nodes: ['debrief', 'trainer', 'scorer'], title: 'Debrief and trainer rubric', detail: 'Ground truth, tactics and coaching are revealed. A blinded trainer can enter the five-dimension rubric.' },
        { nodes: ['bakeoff', 'harness', 'scorer', 'fpgate', 'isolation', 'leaderboard'], title: 'Bake-off gates and leaderboards', detail: 'Across many trials, candidates must pass the 5% false-positive gate and the isolation check before being ranked on recall, then questioning quality.', tone: 'control' },
      ],
    }
  }
  if (tab === 'loops') {
    return {
      intro: 'Five nested loops, innermost first. Each has a budget, an exit condition and a measurement, and each discipline points at the modules where it is applied.',
      steps: [
        { nodes: ['agentloop', 'harnessd', 'llm', 'profiles', 'cand'], title: 'Agent loop (deepagents)', detail: 'Inside every call: the model acts, calls lookup_turn / list_released_evidence / get_case_packet, observes, acts again until it emits JSON. Harness engineering restricts the tool set.' },
        { nodes: ['L0', 'val', 'loopd', 'agentloop'], title: 'L0 validation loop', detail: 'Parse the output, validate against the Pydantic schema, re-prompt with the exact error. Two retries, then degrade to a conservative result. validation_loop.py' },
        { nodes: ['L1', 'llm', 'prompt', 'prompts', 'loopd', 'L0'], title: 'L1 rubric loop', detail: 'RubricMiddleware: a grader model checks the coaching against the rubric (exact citations, no demeanor inference, neutral follow-up) and the assistant revises up to the iteration cap. Prompt engineering owns the rubrics. llm.py' },
        { nodes: ['L2', 'il', 'context', 'ctx', 'loopd', 'L1'], title: 'L2 interview loop', detail: 'Question, answer, assessment, scripted evidence release, budget check, lock, score. Context engineering decides what crosses into the assistant each turn. interview_loop.py' },
        { nodes: ['L3', 'bl', 'sc', 'loopd', 'L2', 'cand'], title: 'L3 bake-off loop', detail: 'Freeze candidates, replay identical transcripts, cross-pair in live interviews, score blind, apply gates, rank. bakeoff_loop.py, scoring.py' },
        { nodes: ['L4', 'sc', 'loopd', 'L3'], title: 'L4 investigator loop', detail: 'Each locked session updates the questioning score; progress is measured against the investigator’s own first session toward +20%. scoring.py' },
      ],
    }
  }
  if (tab === 'case' && c) {
    const topics = c.key_topics
    return {
      intro: `What the investigator knows before the first question, and the lines of questioning the case is built around. Role and scoring key stay hidden.`,
      steps: [
        { nodes: ['case', 'objective'], title: 'Objective', detail: c.objective },
        { nodes: ['case'], title: 'Context', detail: c.context },
        { nodes: c.known_timeline.map((_, i) => `tl${i}`), title: 'Known timeline', lines: c.known_timeline },
        { nodes: c.initial_documents.map((d) => d.id), title: `Initial record${c.initial_documents.length > 1 ? 's' : ''}`, detail: c.initial_documents.map((d) => `${d.id} ${d.title}: ${d.content}`).join(' ') },
        { nodes: ['case'], title: 'Suggested opening', detail: `“${c.initial_question}”` },
        ...topics.map((t, i) => ({ nodes: [`t_${t}`], title: `Line ${i + 1}: ${t.replace('_', ' ')}`, detail: c.question_bank[t], tone: 'topic' })),
        { nodes: c.initial_documents.map((d) => d.id), title: 'Scripted releases', detail: 'Further records are released after exchanges 2 and 4. Return to an open point once a record contradicts an earlier answer.' },
        { nodes: ['case'], title: 'Budget and closure', detail: `Up to ${c.max_turns} exchanges, then lock a finding. Prefer not enough evidence to an unsupported accusation.` },
      ],
    }
  }
  if (tab === 'session' && s) {
    const steps = s.turns.map((t) => {
      const flags = t.coaching?.flags || []
      const parts = [`Q: ${t.question}`, `A (${t.tactic || 'hidden'}): ${t.answer}`]
      if (t.coaching) parts.push(`Question quality ${t.coaching.question_quality}/4 · interim ${t.coaching.interim_finding.replace('_', ' ')} ${(t.coaching.confidence * 100).toFixed(0)}%`)
      if (flags.length) parts.push(`Flags: ${flags.map((f) => `${f.kind.replace('_', ' ')} on T${f.turn_index}`).join('; ')}`)
      if (t.evidence_released.length) parts.push(`Released after this turn: ${t.evidence_released.map((e) => `${e.id} ${e.title}`).join(', ')}`)
      const nodes = [`T${t.index}`, ...flags.map((f, j) => `f${t.index}_${j}`), ...flags.map((f) => `T${f.turn_index}`), ...t.evidence_released.map((e) => e.id)]
      return { nodes, title: `Turn ${t.index}`, lines: parts, tone: flags.some((f) => f.kind === 'contradiction') ? 'contradiction' : flags.length ? 'flag' : 'turn' }
    })
    const lastT = s.turns.length ? `T${s.turns[s.turns.length - 1].index}` : 'case'
    if (s.final_finding) steps.push({ nodes: ['inv', lastT], title: 'Investigator locks a finding', detail: `${s.final_finding.finding.replace('_', ' ')} at ${Math.round(s.final_finding.confidence * 100)}%${s.final_finding.rationale ? ` — ${s.final_finding.rationale}` : ''}`, tone: 'finding' })
    if (s.assistant_final) steps.push({ nodes: ['asst', lastT], title: 'Assistant locks its own finding', detail: `${s.assistant_final.finding.replace('_', ' ')} at ${Math.round(s.assistant_final.confidence * 100)}% — ${s.assistant_final.rationale}`, tone: 'finding' })
    if (s.debrief) {
      const d = s.debrief
      steps.push({ nodes: ['truth', 'inv', 'asst', 'case'], title: 'Scorer reveals ground truth', detail: `${d.ground_truth_role}${d.violation ? ` — ${d.violation}` : ' — no violation'}. Investigator ${d.investigator_correct ? 'correct' : 'incorrect'}${d.assistant_correct !== null ? `, assistant ${d.assistant_correct ? 'correct' : 'incorrect'}` : ''}. Questioning score ${d.investigator_auto_score}, evasion flags P/R ${d.evasion_precision === null ? 'n/a' : Math.round(d.evasion_precision * 100) + '%'} / ${d.evasion_recall === null ? 'n/a' : Math.round(d.evasion_recall * 100) + '%'}, isolation ${d.isolation_pass ? 'pass' : 'fail'}.`, tone: d.investigator_correct ? 'evidence' : 'contradiction' })
    }
    return { intro: `Session ${s.id}: ${s.investigator} on ${s.case_id} in ${s.mode} mode, ${s.turns.length} of ${s.max_turns} exchanges used.`, steps }
  }
  return null
}
