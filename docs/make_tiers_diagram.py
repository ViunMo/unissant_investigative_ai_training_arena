"""Generate architecture-tiers.svg: the tiered architecture diagram with vector icons.

Run:    python docs/make_tiers_diagram.py
PNG:    render the SVG with a headless browser, e.g.
        chrome --headless=new --screenshot=docs/architecture-tiers.png --window-size=1600,1330 \
               --force-device-scale-factor=2 docs/architecture-tiers.svg
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "architecture-tiers.svg"

W, H = 1600, 1330
LABEL_X, CONTENT_X, CONTENT_W = 40, 240, 1140
BAND_H, GAP, TOP = 160, 34, 104
CROSS_X, CROSS_W = 1400, 160

ICONS = {
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "nodes": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 7.5l3 8M16 7.5l-3 8M8.5 6h7"/>',
    "chat": '<path d="M4 5h16v10H9l-5 4z"/>',
    "chart": '<path d="M5 19v-7M10 19V7M15 19v-9M20 19V4M3 21h18"/>',
    "trophy": '<path d="M8 4h8v5a4 4 0 0 1-8 0zM6 6H4a3 3 0 0 0 3 3M18 6h2a3 3 0 0 1-3 3M12 13v4m-4 3h8"/>',
    "folder": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "shield": '<path d="M12 3l7 3v5c0 4.8-3 8.4-7 10-4-1.6-7-5.2-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    "code": '<path d="M9 8l-4 4 4 4M15 8l4 4-4 4M13 5l-2 14"/>',
    "eyeoff": '<path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 21 12a10.5 10.5 0 0 1-2.4 3.2M6.6 6.6A10.5 10.5 0 0 0 3 12a10 10 0 0 0 11 6.9"/>',
    "gears": '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "loop": '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4"/>',
    "robot": '<rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9.5 16h5"/>',
    "doc": '<path d="M6 3h8l4 4v14H6zM14 3v4h4M9 12h6M9 16h6"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "db": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    "people": '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 14.2c2.9.3 5.5 2.7 5.5 5.8"/>',
    "key": '<circle cx="8" cy="14" r="4"/><path d="M11 11l9-9M17 5l3 3M14 8l2 2"/>',
    "chip": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    "gauge": '<path d="M4 16a8 8 0 0 1 16 0M12 16l4-5"/><circle cx="12" cy="16" r="1.5"/>',
    "chain": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5"/>',
    "coins": '<ellipse cx="10" cy="7" rx="6" ry="2.5"/><path d="M4 7v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V7M8 14v3c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4M20 13c0-1.2-1.8-2.2-4.5-2.5"/>',
    "cloud": '<path d="M7 18a4 4 0 0 1-.6-8A6 6 0 0 1 18 9.5 4 4 0 0 1 17.5 18z"/>',
    "server": '<rect x="4" y="4" width="16" height="6" rx="1.5"/><rect x="4" y="14" width="16" height="6" rx="1.5"/><path d="M8 7h.01M8 17h.01"/>',
    "graph": '<circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="7" r="2.5"/><circle cx="12" cy="17" r="2.5"/><circle cx="18" cy="17" r="2"/><path d="M9.5 7h5M8.3 9l2.5 6M15.7 9l-2.5 6M14.5 17h1.5"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "api": '<path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5"/>',
    "brain": '<path d="M9 4a3 3 0 0 0-3 3v1a3 3 0 0 0-1 5.8V15a3 3 0 0 0 3 3h1a2 2 0 0 0 4 0h1a3 3 0 0 0 3-3v-1.2A3 3 0 0 0 18 8V7a3 3 0 0 0-3-3h-1a2 2 0 0 0-4 0zM12 4v16"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
}

TIERS = [
    dict(num="01", name="Presentation tier", sub="Frontend", icon="monitor", color="#1e5bd8", tint="#e8f0fd",
         caption="React 19 + Vite on :5173 · Unissant typeface and gold accent · api.js adds Authorization: Bearer and sends a 401 back to the login page",
         cards=[("Login", "lock", ["sign in or register", "token in localStorage"]),
                ("Overview", "nodes", ["KPIs, knowledge graphs", "d3-force, Neo4j tab"]),
                ("Practice", "chat", ["chat, avatars, typing", "coaching, lock, debrief"]),
                ("Sessions", "chart", ["history, score chart", "+20% vs own baseline"]),
                ("Bake-off", "trophy", ["live feed, stop, clear", "leaderboards, gates"]),
                ("Scenarios", "folder", ["public case packets", "role never shown"])]),
    dict(num="02", name="API tier", sub="Backend", icon="api", color="#5b4fcf", tint="#edebfb",
         caption="FastAPI on :8000 · CORS for the dev server · every route except /health and /auth/* requires a bearer token",
         cards=[("Authentication", "shield", ["auth.py: PBKDF2 password hashes,", "HMAC-signed tokens, 12 h expiry"]),
                ("REST routes", "code", ["api/routes.py: sessions, findings,", "bake-offs, graph, candidates, health"]),
                ("Hidden-until-lock views", "eyeoff", ["roles, tactics and scoring keys", "appear only after a finding is locked"]),
                ("Background work", "gears", ["ThreadPoolExecutor: bake-off runs,", "Neo4j mirroring after each lock"])]),
    dict(num="03", name="Service layer", sub="Domain logic", icon="layers", color="#0f8f7a", tint="#e6f6f2",
         caption="Candidate registry: model + prompt version + tools + policy · HarnessProfile removes filesystem, shell and subagent tools · AssistantContext is the isolation boundary",
         cards=[("Interview loop  L2", "loop", ["question, answer, coach,", "evidence release, lock"]),
                ("Bake-off loop  L3", "trophy", ["frozen, replay, interactive", "thread pool, stop, blind score"]),
                ("Agent runtimes", "robot", ["deepagents assistant / subject", "mock rules, L0 and L1 loops"]),
                ("Scenario engine", "doc", ["3 families x 2 variants", "locked packets, releases"]),
                ("Independent scorer", "check", ["debrief, evasion P/R, gates", "bootstrap CIs, progress"])]),
    dict(num="04", name="Data layer", sub="Persistence", icon="db", color="#556b8a", tint="#eef1f6",
         caption="backend/data (gitignored) · configuration in backend/.env via pydantic-settings, where .env takes precedence over the OS environment",
         cards=[("JSON store", "doc", ["store.py: sessions, bake-offs,", "one snapshot file per record"]),
                ("Users and secrets", "people", ["data/users.json (hashes),", "data/secret.key (token signing)"]),
                ("Response cache", "db", ["llm_cache.sqlite keyed on the", "conversation; hits cost nothing"]),
                ("Evidence graph", "graph", ["graph.py mirrors locked sessions", "to Neo4j; Cypher insights, rebuild"])]),
    dict(num="05", name="Model layer", sub="LLM access", icon="brain", color="#a9731a", tint="#fdf6e6",
         caption="llm.py · one LangChain chat model per candidate (model id + effort) · identical calls served from the cache before any vendor is contacted",
         cards=[("Model factory", "chip", ["build_chat_model: vendor from the", "model id, effort, max tokens"]),
                ("Rate limiters", "gauge", ["one token bucket per vendor", "Gemini free tier: 14 per minute"]),
                ("LangChain deepagents", "chain", ["tool loop, RubricMiddleware,", "Anthropic prompt caching"]),
                ("Price table", "coins", ["USD per MTok per model id", "cost column, zero on cache hits"])]),
    dict(num="06", name="External services", sub="Cloud", icon="globe", color="#b8860b", tint="#fff8e6", external=True,
         caption="credentials only in backend/.env · the gateway option replaces the three vendors with any OpenAI-compatible endpoint",
         cards=[("OpenAI", "cloud", ["gpt-6-luna", "reasoning_effort, no temperature"]),
                ("Anthropic", "cloud", ["claude-haiku-5-5", "adaptive thinking + effort"]),
                ("Google Gemini", "cloud", ["gemini-3.5-flash-lite", "fixed sampling, effort"]),
                ("Compatible gateway", "server", ["any OpenAI-compatible API,", "e.g. a local Ollama server"]),
                ("Neo4j Aura", "graph", ["cross-session evidence graph", "neo4j+s:// (bolt)"])]),
]

FLOWS = ["HTTPS /api · JSON · Authorization: Bearer", "services invoked per request or in a background thread",
         "save sessions and runs · look up the response cache · mirror locked sessions",
         "chat model per candidate · effort · rate limiter · cache miss only",
         "HTTPS to vendor APIs"]

CROSS = [("Security and isolation", "shield", ["bearer authentication", "hidden-until-lock views", "canary scan of every", "assistant input", "private packet never", "leaves the backend", "keys only in .env"]),
         ("Observability", "chart", ["live feed of every", "model call (bake-off)", "latency and cost", "per coaching call", "cache hit statistics", "health endpoint"]),
         ("Quality loops", "loop", ["L0 validation: parse,", "validate, re-prompt", "L1 rubric: grader,", "revise", "L3 blind scoring,", "5% FP gate, CIs"])]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def icon(name, x, y, size, color):
    return (f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')


parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         'font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">',
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
         '<path d="M0 0L10 5 0 10z" fill="#335a92"/></marker>'
         '<marker id="arrg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
         '<path d="M0 0L10 5 0 10z" fill="#b8860b"/></marker>'
         '<filter id="shadow" x="-5%" y="-5%" width="110%" height="120%"><feDropShadow dx="0" dy="1.5" stdDeviation="1.5" flood-color="#0e2246" flood-opacity="0.12"/></filter>'
         '</defs>',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
         '<text x="40" y="44" font-size="24" font-weight="700" fill="#143a7a">Investigative AI Training Arena · tiered architecture</text>',
         '<text x="40" y="68" font-size="13" fill="#4a5a73">Six tiers from the browser to the model vendors, with the cross-cutting concerns on the right. '
         'Every flow is also drawn as Mermaid in architecture.md.</text>']

band_ys = []
for i, t in enumerate(TIERS):
    y = TOP + i * (BAND_H + GAP)
    band_ys.append(y)
    parts.append(f'<rect x="{LABEL_X}" y="{y}" width="{CONTENT_X + CONTENT_W - LABEL_X}" height="{BAND_H}" rx="14" fill="{t["tint"]}" stroke="{t["color"]}" stroke-opacity="0.35" stroke-width="1.2"/>')
    # label column
    parts.append(f'<rect x="{LABEL_X}" y="{y}" width="180" height="{BAND_H}" rx="14" fill="{t["color"]}"/>')
    parts.append(f'<rect x="{LABEL_X + 150}" y="{y}" width="30" height="{BAND_H}" fill="{t["color"]}"/>')
    parts.append(f'<text x="{LABEL_X + 18}" y="{y + 34}" font-size="26" font-weight="700" fill="#ffffff" fill-opacity="0.55">{t["num"]}</text>')
    parts.append(icon(t["icon"], LABEL_X + 128, y + 14, 30, "#ffffff"))
    parts.append(f'<text x="{LABEL_X + 18}" y="{y + 70}" font-size="15" font-weight="700" fill="#ffffff">{esc(t["name"])}</text>')
    parts.append(f'<text x="{LABEL_X + 18}" y="{y + 90}" font-size="12" fill="#ffffff" fill-opacity="0.85">{esc(t["sub"])}</text>')
    # cards
    n = len(t["cards"]); gap = 14
    cw = (CONTENT_W - gap * (n - 1)) / n
    cy, ch = y + 16, 104
    for j, (title, ic, lines) in enumerate(t["cards"]):
        cx = CONTENT_X + j * (cw + gap)
        fill = "#fff8e6" if t.get("external") else "#ffffff"
        stroke = t["color"] if t.get("external") else "#c9d3e3"
        parts.append(f'<rect x="{cx:.0f}" y="{cy}" width="{cw:.0f}" height="{ch}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.1" filter="url(#shadow)"/>')
        parts.append(f'<circle cx="{cx + 28:.0f}" cy="{cy + 28}" r="18" fill="{t["tint"]}"/>')
        parts.append(icon(ic, cx + 17, cy + 17, 22, t["color"]))
        parts.append(f'<text x="{cx + 54:.0f}" y="{cy + 32}" font-size="13.5" font-weight="700" fill="#0e2246">{esc(title)}</text>')
        for k, line in enumerate(lines):
            parts.append(f'<text x="{cx + 14:.0f}" y="{cy + 66 + k * 17}" fill="#334155">{esc(line)}</text>')
    parts.append(f'<text x="{CONTENT_X}" y="{y + BAND_H - 14}" font-size="11.5" fill="#4a5a73">{esc(t["caption"])}</text>')

# flows between tiers
for i, label in enumerate(FLOWS):
    y0 = band_ys[i] + BAND_H; y1 = band_ys[i + 1]
    x = CONTENT_X + 40
    marker = "arrg" if i == 4 else "arr"; col = "#b8860b" if i == 4 else "#335a92"
    parts.append(f'<path d="M{x} {y0 + 2} L{x} {y1 - 2}" stroke="{col}" stroke-width="1.8" fill="none" marker-end="url(#{marker})"/>')
    parts.append(f'<text x="{x + 14}" y="{(y0 + y1) / 2 + 4:.0f}" font-size="11.5" fill="#4a5a73">{esc(label)}</text>')
xl = CONTENT_X - 10  # service layer (Agent runtimes card) -> model layer (Model factory card), left gutter
parts.append(f'<path d="M{CONTENT_X} {band_ys[2] + 68} L{xl} {band_ys[2] + 68} L{xl} {band_ys[4] + 68} L{CONTENT_X - 1} {band_ys[4] + 68}" stroke="#0f8f7a" stroke-width="1.6" fill="none" marker-end="url(#arr)"/>')
xr = CONTENT_X + CONTENT_W + 10  # data layer (Evidence graph card) -> Neo4j Aura card, right gutter
parts.append(f'<path d="M{CONTENT_X + CONTENT_W} {band_ys[3] + 68} L{xr} {band_ys[3] + 68} L{xr} {band_ys[5] + 68} L{CONTENT_X + CONTENT_W + 1} {band_ys[5] + 68}" stroke="#b8860b" stroke-width="1.6" fill="none" marker-end="url(#arrg)"/>')

# cross-cutting column
top, bottom = band_ys[0], band_ys[-1] + BAND_H
parts.append(f'<rect x="{CROSS_X}" y="{top}" width="{CROSS_W}" height="{bottom - top}" rx="14" fill="#f4f7fc" stroke="#143a7a" stroke-opacity="0.35" stroke-width="1.2"/>')
parts.append(f'<text x="{CROSS_X + 14}" y="{top + 28}" font-size="13.5" font-weight="700" fill="#143a7a">Cross-cutting</text>')
cy = top + 50
for title, ic, lines in CROSS:
    parts.append(f'<rect x="{CROSS_X + 10}" y="{cy}" width="{CROSS_W - 20}" height="{54 + 17 * len(lines)}" rx="10" fill="#ffffff" stroke="#c9d3e3" stroke-width="1.1" filter="url(#shadow)"/>')
    parts.append(f'<circle cx="{CROSS_X + 34}" cy="{cy + 24}" r="15" fill="#e8f0fd"/>')
    parts.append(icon(ic, CROSS_X + 24, cy + 14, 20, "#143a7a"))
    parts.append(f'<text x="{CROSS_X + 56}" y="{cy + 20}" font-size="12.5" font-weight="700" fill="#0e2246">{esc(title.split(" and ")[0])}</text>')
    if " and " in title:
        parts.append(f'<text x="{CROSS_X + 56}" y="{cy + 35}" font-size="12.5" font-weight="700" fill="#0e2246">and {esc(title.split(" and ")[1])}</text>')
    for k, line in enumerate(lines):
        parts.append(f'<text x="{CROSS_X + 20}" y="{cy + 58 + k * 17}" fill="#334155" font-size="11.5">{esc(line)}</text>')
    cy += 54 + 17 * len(lines) + 18

# legend
ly = bottom + 36
parts.append(f'<rect x="40" y="{ly - 11}" width="14" height="14" rx="3" fill="#ffffff" stroke="#c9d3e3"/><text x="62" y="{ly}" fill="#334155">application component</text>')
parts.append(f'<rect x="230" y="{ly - 11}" width="14" height="14" rx="3" fill="#fff8e6" stroke="#b8860b"/><text x="252" y="{ly}" fill="#334155">external service</text>')
parts.append(f'<path d="M380 {ly - 4} L420 {ly - 4}" stroke="#335a92" stroke-width="1.8" marker-end="url(#arr)"/><text x="430" y="{ly}" fill="#334155">request / data flow</text>')
parts.append(f'<path d="M580 {ly - 4} L620 {ly - 4}" stroke="#0f8f7a" stroke-width="1.6" marker-end="url(#arr)"/><text x="630" y="{ly}" fill="#334155">service layer calling the model layer directly</text>')
parts.append(f'<path d="M950 {ly - 4} L990 {ly - 4}" stroke="#b8860b" stroke-width="1.6" marker-end="url(#arrg)"/><text x="1000" y="{ly}" fill="#334155">data layer mirroring to Neo4j Aura</text>')
parts.append("</svg>")
OUT.write_text("\n".join(parts), encoding="utf-8")
print("wrote", OUT, "height", H)
