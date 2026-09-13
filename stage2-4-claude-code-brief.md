# Stages 2-4 — Claude Code Handoff (build all three tonight)

Stage 1 is done/in progress (real hospital data loading into Tiger Data).
This brief covers the rest of the app: price lookup, bill translation, and
the procedure/medication explainer — wired through the existing agent
architecture in `app/services/agent_service.py` rather than three separate
hardcoded routes.

## Priority order (build in this sequence, get each working before moving on)

### 1. Stage 2 — Hospital + procedure price lookup
- Flesh out `app/routes/hospital_lookup.py` using the now-real
  `db_service.search_hospitals()` / `get_prices()`.
- Frontend: replace the "Coming soon" placeholder in
  `app/templates/index.html` with a simple search box (hospital name) +
  results list showing gross/cash/negotiated price range for a procedure.
- Test against 2-3 real hospitals we already confirmed have data loaded.

### 2. Stage 3 — Bill upload & translate (headline feature, get this solid)
- Wire up `app/services/gemini_service.py`'s `extract_bill_line_items()`
  for real: send the uploaded image/PDF to Gemini, prompt it to return
  strict JSON: `[{code, description, charge}, ...]`. Use Gemini's
  multimodal input directly — check current docs at
  ai.google.dev/gemini-api/docs for the exact current SDK call syntax
  rather than guessing from memory, since this shifts between versions.
- For each extracted line item, cross-reference against loaded hospital
  price data (Stage 2's `get_prices()`) when the hospital is one we have,
  and call `explain()` (Stage 4 below) to translate it to plain language.
- Frontend: file upload input + results showing each line item translated,
  with the price comparison where available.

### 3. Stage 4 — Procedure/medication explainer
- Wire up `gemini_service.explain(query, mode, lang)` for real: send the
  term to Gemini, ask for a plain-language explanation (patient mode) or
  clinical explanation (doctor mode), include side effects for medications.
- Frontend: simple text box + mode toggle, already stubbed in the template.
- This same function is reused by Stage 3 for translating bill line items
  — don't duplicate the prompt logic.

### On the agent layer (agent_service.py)
Keep it — don't rip it out. But prioritize: get the three routes above
working with DIRECT calls first (proven, debuggable), then wire
`run_agent()` to orchestrate them via Gemini function calling as a second
pass once the underlying functions are solid. If time runs out before the
agent loop is finished, the three direct routes are a completely valid
fallback demo path — the direct routes should never depend on the agent
working.

## Constraints
- Submission deadline is ~9 AM. Work efficiently; flag blockers immediately
  rather than getting stuck silently.
- Test against real hospitals we already have loaded rather than synthetic
  data, so the demo is showing something genuinely true.
- Keep committing to git in reasonable chunks as pieces become solid
  (ask before each commit, per usual workflow) — don't let uncommitted
  work pile up all night in case something needs to be rolled back.
