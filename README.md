# BillClear — Hospital Price Transparency & Bill Translator

HackRice 16 (Sept 11–13, 2026) — Healthcare track submission.

## What it does

1. **Hospital price lookup**: search a supported hospital + procedure and see
   the gross charge, cash price, and negotiated rate range from that
   hospital's federally-mandated price transparency file (MRF).
2. **Bill translator**:  upload a photo/PDF of a hospital bill and get each
   line item explained in plain language, with a comparison against that
   hospital's own posted prices where available.
3. **Procedure / medication explainer**: look up a procedure or medication
   and get a plain-language explanation of what it is, why it's done, and
   side effects.

## Architecture

Gemini runs as an orchestrating agent (function calling / tool use), not a
set of hardcoded prompts. It has three tools available — extract bill line
items, look up a hospital's posted price for a procedure, and explain a
term in plain language — and decides which to call and in what order based
on what the user asked or uploaded. E.g. uploading a bill triggers
extraction, then a price lookup and explanation per line item, all in one
agent run, without the frontend needing separate calls for each step.
See `app/services/agent_service.py`.

The three individual routes (`/api/hospital`, `/api/bill`, `/api/explain`)
are kept as direct fallbacks for testing and demo reliability.

## Sponsor challenges targeted

- Best Use of Gemini API: bill parsing (multimodal extraction), plain-language
  explanations, price-gap narration.
- Best Use of Tiger Data: normalized hospital price data stored and queried
  in Postgres/Tiger Data for fast lookups.
- Best Domain Name from GoDaddy Registry.

## Stack

- Backend: Python (FastAPI)
- Frontend: plain HTML/JS (Tailwind via CDN, no build step)
- Database: Postgres (Tiger Data)
- AI: Gemini API (multimodal bill parsing + explanations)

## Data sources

Hospital price data pulled from each hospital's CMS-mandated machine-readable
file (45 CFR Part 180). See `data/hospitals.json` for the pre-vetted list of
hospitals used in this demo.

## Project status

Built during HackRice 16 (Sept 11–13, 2026). See commit history for build
timeline.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own API keys — never commit .env
uvicorn app.main:app --reload
```

## Not medical or legal advice

This tool explains publicly available pricing and general information about
procedures/medications. It is not medical or legal advice, and does not
guarantee accuracy of any hospital's self-reported pricing data.
