# Investigative AI Training Arena

A text-based training arena where investigators practice interviews with simulated subjects while competing
AI assistants coach them. Built for the Unissant use case "Investigative AI Training Arena: Multi-Agent
Interview Coaching and Evaluation".

- **Backend:** Python 3.12, FastAPI, [LangChain deepagents](https://docs.langchain.com/oss/python/deepagents).
- **Models:** any OpenAI-compatible gateway (the challenge-provided `gpt-oss-20b` endpoint is the default
  configuration) or Anthropic Claude. The provider is chosen in `backend/.env`.
- **Frontend:** React 19 + Vite.
- **Runs offline:** with no model credentials every candidate falls back to a deterministic mock runtime,
  so the full interview, debrief and bake-off flows (and the test suite) work with no model calls.

All cases, people, companies and records are synthetic.

Docs: [architecture.md](architecture.md) (components, loops, engineering disciplines) and [app_usage.md](app_usage.md) (how to use the app, with flow diagrams).

## Quick start

One command for both servers (creates the venv and installs frontend dependencies on first run):

```bash
./start.sh          # backend :8000 + frontend :5173, logs and pids in .run/
./stop.sh           # stop both (./start.sh backend | ./stop.sh frontend for one side)
```

Manual steps:

```bash
# backend
cd backend
uv venv --python 3.12 .venv && .venv/bin/python -m pip install -r requirements.txt   # or: uv pip install -r requirements.txt
cp .env.example .env            # set ARENA_OPENAI_BASE_URL / ARENA_OPENAI_API_KEY / ARENA_OPENAI_MODEL (or ANTHROPIC_API_KEY)
./run_dev.sh                    # http://localhost:8000  (OpenAPI docs at /docs)

# frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173  (proxies /api to :8000)

# tests
cd backend && .venv/bin/python -m pytest -q
```

`run_dev.sh` calls the venv interpreter by path on purpose: a shell alias for `python` can otherwise bypass the venv.

## How it maps to the challenge

| Challenge requirement | Where it lives |
|---|---|
| Investigative assistants that flag gaps/contradictions with transcript evidence and suggest neutral follow-ups | `backend/app/agents/llm.py` (`DeepAgentAssistant`), prompt in `app/agents/prompts.py`, baseline rules in `app/agents/mock.py` |
| Simulated subjects playing truthful or deceptive roles from a private profile | `DeepAgentSubject`, `MockSubject`; private packets in `app/scenarios/library.py` |
| Scenario engine: locked facts, scripted evidence release, hidden role labels and scoring keys | `app/scenarios/engine.py`; three packets per case (public / private subject / evaluator-only) |
| Independent scoring of the locked finding against hidden facts | `app/scoring/scoring.py` |
| Practice vs assessment modes | `Session.mode`; the API withholds coaching in assessment mode until the finding is locked |
| Bake-off: 3 assistants × 3 subjects, replay then interactive track, blinded scoring | `app/loops/bakeoff_loop.py` |
| Isolation (no access to hidden answers) and 5% false-positive gates, then rank on recall and questioning | `aggregate_assistants` in `app/scoring/scoring.py` |
| Investigator improvement vs own baseline (+20%) | `investigator_progress`; Sessions page |
| Case-level clustering in confidence intervals, role prevalence disclosure | `cluster_bootstrap_recall_ci`, `BakeoffRun.role_prevalence` |

## Loop engineering

The arena is organised as five nested, bounded loops. Each has an explicit budget, exit condition and measurement.

| Loop | What iterates | Budget / exit | Code |
|---|---|---|---|
| **L0 Validation loop** | Model output → parse → validate as a Pydantic schema → re-prompt with the error | 2 retries, then raise | `app/agents/validation_loop.py` |
| **L1 Rubric loop** | deepagents `RubricMiddleware`: a grader model checks the assistant's coaching against a rubric (exact turn citations, no demeanor inference, neutral follow-up) and the assistant revises | `rubric_max_iterations` per candidate policy | `DeepAgentAssistant._agent` |
| **L2 Interview loop** | question → subject answer → assistant assessment → scripted evidence release → budget check → commit → score | `max_turns` exchanges; ends when a finding is locked | `app/loops/interview_loop.py` |
| **L3 Bake-off loop** | frozen transcripts → replay track → interactive cross-pairing → blind scoring → gates → leaderboards | cases × candidates × repeats × tracks, randomised order | `app/loops/bakeoff_loop.py` |
| **L4 Investigator loop** | each locked session updates the investigator's questioning score against their own first session | target +20% | `investigator_progress` |

## Agents (deepagents)

Both agent categories are built with `create_deep_agent`:

- **Assistant** gets three read-only tools (`lookup_turn`, `list_released_evidence`, `get_case_packet`) so every
  flag can quote an exact turn. A `HarnessProfile` removes deepagents' default filesystem, shell and subagent tools.
  The candidate policy decides the model, effort and whether the rubric loop is on.
- **Subject** gets its private packet in the system prompt and reports a `tactic` for each turn
  (`truthful | uncertain | omission | deflection | minimisation | contradiction`). The scorer uses those labels as
  evasion-event ground truth; they are never shown to assistants. Behaviour outside the permitted list, or
  disclosure of a must-not-disclose fact, is a fidelity failure, not successful evasion.
- Models are built by `build_chat_model` in `app/agents/llm.py`:
  - `ARENA_PROVIDER=openai_compatible` (default when the gateway variables are set): `ChatOpenAI` pointed at
    `ARENA_OPENAI_BASE_URL` with `ARENA_OPENAI_MODEL` (tested with `gpt-oss-20b`, which supports tool calls and
    `reasoning_effort`). The candidate policy's `effort` maps to `reasoning_effort`.
  - `ARENA_PROVIDER=anthropic`: `claude-opus-5-5` with adaptive thinking, explicit effort and server-side
    refusal fallbacks; `claude-sonnet-5-5` as the rubric grader.
  - `ARENA_PROVIDER=mock`: deterministic rule-based runtimes, no network.
- Observed on the gateway model: the fast candidate coaches in roughly 4-5 s per turn; the rubric-loop candidate
  takes 20-75 s per turn because the grader re-runs the agent. The leaderboard publishes both latencies.

Candidates are versioned combinations of model + prompt version + tool configuration + policy
(`app/agents/candidates.py`): `asst-evidence-v1` (rubric loop on), `asst-fast-v1` (rubric loop off, low effort),
`subj-llm-v1`, `subj-llm-medium-v1`, plus the mock baselines below. Two deterministic baselines ship on purpose: an evidence-first rule set that respects
the false-positive constraint, and an aggressive rule set that treats uncertainty as evasion and is expected to
fail the 5% gate.

## Isolation

`AssistantContext` is the boundary: it is built only from the public packet, the transcript and released
records. Every string an assistant receives is logged to `Session.assistant_inputs`; the scorer scans that log for
evaluator-only canary strings (role markers, private objectives). A candidate that fails the check is ineligible.

## Scoring summary

- **Role score:** 2×3 matrix (truthful/deceptive × truthful/deceptive/insufficient), deceptive recall with a
  family-clustered bootstrap CI, false-positive rate with unresolved truthful cases kept in the denominator, PPV,
  unresolved rates by role.
- **Evasion events:** precision/recall of `possible_evasion`, `non_responsive` and `contradiction` flags against
  the subject's tactic labels; flags with no quote or a non-existent turn count as unsupported.
- **Questioning quality (proxy):** topic coverage × (1 − unsupported-flag rate). The five-dimension trainer rubric
  (0–4 each, ×5) is entered by a blinded trainer on the debrief screen and must be calibrated locally before use.
- **Subjects:** fidelity (compliant turns / all turns) reported separately for truthful and deceptive runs,
  invalid sessions, deceptive success (undetected within budget while compliant), misleading clearance, unresolved.
- **Eligibility:** false-positive rate ≤ 5% and isolation pass. Eligible candidates rank by recall, then
  questioning quality. Cost and latency are published alongside rank.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | provider, model ids, gateway URL, case count |
| GET | `/api/scenarios` | public packets only |
| GET | `/api/candidates?kind=assistant\|subject` | candidate specs and their effective runtime |
| POST | `/api/sessions` | start (mode, case or random, assistant, subject, budget) |
| POST | `/api/sessions/{id}/ask` | one exchange; coaching returned only in practice mode |
| POST | `/api/sessions/{id}/finding` | lock the finding; returns the debrief with revealed facts |
| POST | `/api/sessions/{id}/trainer-rating` | blinded trainer rubric |
| GET | `/api/investigators/{name}/progress` | baseline vs recent sessions |
| POST | `/api/bakeoffs` | start a tournament (runs in the background) |
| GET | `/api/bakeoffs/{id}?include_results=true` | status, leaderboards, per-trial results |

## Project layout

```
backend/app
  config.py            settings (provider auto|openai_compatible|anthropic|mock, model ids)
  schemas.py           all Pydantic models
  scenarios/           library.py (3 families × 2 variants), engine.py
  agents/              context.py (isolation boundary), llm.py (deepagents), mock.py, candidates.py,
                       prompts.py, profiles.py, validation_loop.py
  loops/               interview_loop.py (L2), bakeoff_loop.py (L3)
  scoring/scoring.py   debrief, trial results, leaderboards, bootstrap CI, progress
  api/routes.py        FastAPI routes;  main.py app factory
backend/tests          29 tests, all runnable offline
frontend/src           sidebar app shell; pages: Home (KPIs + knowledge graphs), Practice (stepper), Sessions (progress chart),
                       Bakeoff (leaderboards), Scenarios; components: KnowledgeGraph (d3-force), ScoreChart, Coaching, Debrief
```

## Adding a case family

Add a matched truthful and deceptive `Scenario` pair to `app/scenarios/library.py`. Keep communication style
independent of role, give every `question_bank` entry keywords that resolve to its own topic (a test enforces this),
and list only evaluator-only strings as `isolation_canaries`. Put new families on the `hidden` split so they never
appear in development prompts or tuning.
