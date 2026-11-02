import { useMemo, useRef, useState } from 'react'

/**
 * Single-series line chart: questioning score per locked session, with the investigator's baseline
 * and the +20% target as reference lines. One series, so no legend; last point is direct-labelled.
 */
export default function ScoreChart({ history, baseline, targetPct = 20, height = 220 }) {
  const ref = useRef(null)
  const [hover, setHover] = useState(null)
  const width = 720
  const pad = { l: 40, r: 96, t: 22, b: 30 }
  const pts = useMemo(() => {
    const n = history.length
    const x = (i) => pad.l + (n === 1 ? (width - pad.l - pad.r) / 2 : (i * (width - pad.l - pad.r)) / (n - 1))
    const y = (v) => pad.t + (1 - v / 100) * (height - pad.t - pad.b)
    return history.map((h, i) => ({ ...h, x: x(i), y: y(h.score), i }))
  }, [history, height])
  if (!history.length) return null
  const y = (v) => pad.t + (1 - v / 100) * (height - pad.t - pad.b)
  const target = baseline ? Math.min(100, baseline * (1 + targetPct / 100)) : null
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <div className="chart" ref={ref} style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Questioning score by session">
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth="1" />
            <text x={pad.l - 8} y={y(v) + 4} fontSize="10" fill="var(--faint)" textAnchor="end">{v}</text>
          </g>
        ))}
        {baseline !== null && (
          <g>
            <line x1={pad.l} x2={width - pad.r} y1={y(baseline)} y2={y(baseline)} stroke="var(--faint)" strokeWidth="1" strokeDasharray="4 4" />
            <text x={width - pad.r + 6} y={y(baseline) + 4} fontSize="10" fill="var(--muted)">baseline {baseline}</text>
          </g>
        )}
        {target !== null && (
          <g>
            <line x1={pad.l} x2={width - pad.r} y1={y(target)} y2={y(target)} stroke="var(--good)" strokeWidth="1" strokeDasharray="4 4" opacity="0.8" />
            <text x={width - pad.r + 6} y={y(target) + 4} fontSize="10" fill="var(--good)">target {Math.round(target)}</text>
          </g>
        )}
        <path d={path} fill="none" stroke="var(--info)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {pts.map((p) => (
          <g key={p.i} onMouseEnter={() => setHover(p)} onMouseLeave={() => setHover(null)}>
            <circle cx={p.x} cy={p.y} r="12" fill="transparent" />
            <circle cx={p.x} cy={p.y} r={hover?.i === p.i ? 6 : 4.5} fill="var(--info)" stroke="var(--surface)" strokeWidth="2" />
            <text x={p.x} y={height - 10} fontSize="10" fill="var(--faint)" textAnchor="middle">{p.i + 1}</text>
          </g>
        ))}
        <text x={last.x} y={last.y - 12} fontSize="11" fontWeight="600" fill="var(--text)" textAnchor="middle">{last.score}</text>
      </svg>
      {hover && (
        <div className="tip" style={{ left: `${(hover.x / width) * 100}%`, top: `${(hover.y / height) * 100}%` }}>
          <div><b>Session {hover.i + 1}</b> · {hover.case_id} · {hover.mode}</div>
          <div>Score {hover.score}{hover.trainer_score !== null ? ` · trainer ${hover.trainer_score}` : ''} · {hover.correct ? 'correct finding' : 'incorrect finding'}</div>
        </div>
      )}
    </div>
  )
}
