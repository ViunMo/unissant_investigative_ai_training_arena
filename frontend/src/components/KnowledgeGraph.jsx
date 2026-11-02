import { useEffect, useMemo, useRef, useState } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from 'd3-force'

// Validated categorical palette for the dark surface (fixed hue order, never cycled).
const C = { blue: '#3987e5', orange: '#d95926', aqua: '#199e70', yellow: '#c98500', magenta: '#d55181', violet: '#9085e9', gray: '#8d9bb2' }
export const GROUP_COLORS = {
  actor: C.yellow, agent: C.blue, scenario: C.violet, evidence: C.aqua, control: C.magenta, scoring: C.orange,
  loop: C.blue, discipline: C.yellow, module: C.gray,
  turn: C.blue, flag: C.yellow, contradiction: C.magenta, finding: C.orange, topic: C.violet, timeline: C.gray,
}

/**
 * Static force-directed knowledge graph.
 * nodes: [{ id, label, group, size?, title? }]   links: [{ source, target, label? }]
 * badges: optional { nodeId: [stepNumbers] } rendered as a numbered tag on the node (matches the flow panel).
 * Layout is computed once per dataset (simulation ticks run synchronously), so the graph is stable to read.
 */
export default function KnowledgeGraph({ nodes, links, height = 420, legend = true, selected, onSelect, badges }) {
  const ref = useRef(null)
  const [width, setWidth] = useState(900)
  const [internal, setInternal] = useState(null)
  const focus = onSelect ? selected : internal
  const setFocus = onSelect || setInternal

  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver((entries) => setWidth(Math.max(320, entries[0].contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(() => {
    const ns = nodes.map((n) => ({ ...n }))
    const ls = links.map((l) => ({ ...l }))
    // Label-aware collision radius so node captions do not overlap; weak x/y forces spread the
    // graph across the whole canvas instead of clumping at the centre.
    const labelR = (d) => Math.max((d.size || 14) + 18, (d.label.length * 3.9) / 2 + 10)
    const sim = forceSimulation(ns)
      .force('link', forceLink(ls).id((d) => d.id).distance((l) => l.distance || 120).strength(0.5))
      .force('charge', forceManyBody().strength(-520).distanceMax(420))
      .force('center', forceCenter(width / 2, height / 2))
      .force('x', forceX(width / 2).strength(0.045))
      .force('y', forceY(height / 2).strength(0.09))
      .force('collide', forceCollide().radius(labelR).iterations(2))
      .stop()
    for (let i = 0; i < 400; i++) sim.tick()
    const pad = 36
    ns.forEach((n) => { n.x = Math.max(pad, Math.min(width - pad, n.x)); n.y = Math.max(pad, Math.min(height - pad, n.y)) })
    return { ns, ls }
  }, [nodes, links, width, height])

  const neighbours = useMemo(() => {
    if (!focus) return null
    const set = new Set([focus])
    layout.ls.forEach((l) => { if (l.source.id === focus) set.add(l.target.id); if (l.target.id === focus) set.add(l.source.id) })
    return set
  }, [focus, layout])

  const groups = [...new Set(nodes.map((n) => n.group))]
  const dim = (id) => (neighbours && !neighbours.has(id) ? 0.18 : 1)

  return (
    <div ref={ref} className="kg">
      <svg width={width} height={height} role="img" aria-label="knowledge graph" onClick={() => setFocus(null)}>
        <defs>
          <marker id="kg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#5f6d85" />
          </marker>
        </defs>
        {layout.ls.map((l, i) => {
          const op = Math.min(dim(l.source.id), dim(l.target.id))
          const mx = (l.source.x + l.target.x) / 2, my = (l.source.y + l.target.y) / 2
          return (
            <g key={i} opacity={op}>
              <line x1={l.source.x} y1={l.source.y} x2={l.target.x} y2={l.target.y} stroke={l.color || '#5f6d85'} strokeWidth={l.width || 1.2} strokeDasharray={l.dashed ? '4 4' : undefined} markerEnd="url(#kg-arrow)" />
              {l.label && op === 1 && <text x={mx} y={my - 4} fontSize="9" fill="#8d9bb2" textAnchor="middle">{l.label}</text>}
            </g>
          )
        })}
        {layout.ns.map((n) => (
          <g key={n.id} transform={`translate(${n.x},${n.y})`} opacity={dim(n.id)} style={{ cursor: 'pointer' }}
             onClick={(e) => { e.stopPropagation(); setFocus(focus === n.id ? null : n.id) }}>
            <title>{n.title || n.label}</title>
            <circle r={n.size || 14} fill={GROUP_COLORS[n.group] || '#8d9bb2'} fillOpacity={0.22} stroke={GROUP_COLORS[n.group] || '#8d9bb2'} strokeWidth={focus === n.id ? 3 : 1.5} />
            <text y={(n.size || 14) + 12} fontSize="10.5" fill="#e8edf5" textAnchor="middle">{n.label}</text>
            {badges?.[n.id]?.length > 0 && (() => {
              const nums = badges[n.id]
              const text = nums.length <= 3 ? nums.join(',') : `${nums[0]}+`
              const r = n.size || 14
              const w = Math.max(16, text.length * 6 + 8)
              return (
                <g transform={`translate(${r * 0.75},${-r * 0.75})`}>
                  <title>{`Flow step${nums.length > 1 ? 's' : ''} ${nums.join(', ')}`}</title>
                  <rect x={-w / 2} y={-8} width={w} height={16} rx={8} fill="#e8edf5" stroke={GROUP_COLORS[n.group] || '#8d9bb2'} strokeWidth="1.5" />
                  <text y={3.5} fontSize="9.5" fontWeight="700" fill="#0b1220" textAnchor="middle">{text}</text>
                </g>
              )
            })()}
          </g>
        ))}
      </svg>
      {legend && (
        <div className="kg-legend">
          {groups.map((g) => <span key={g}><i style={{ background: GROUP_COLORS[g] || '#8d9bb2' }} />{g}</span>)}
          {badges && <span><i style={{ background: '#e8edf5', borderRadius: 4 }} />flow step number</span>}
          <span className="muted">click a node to focus its neighbours</span>
        </div>
      )}
    </div>
  )
}
