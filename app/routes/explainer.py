"""
Stage 4 — Procedure / medication explainer.

TODO:
- GET /api/explain?query=...&mode=patient|doctor&lang=en
- Send `query` to Gemini asking for a plain-language explanation
  (patient mode) or a more clinical explanation (doctor mode).
- Always include a "not medical advice" disclaimer in the response payload,
  not just the frontend, so any API caller sees it too.
"""

from fastapi import APIRouter

router = APIRouter()

DISCLAIMER = "This is general information, not medical advice."


@router.get("")
def explain(query: str, mode: str = "patient", lang: str = "en"):
    # TODO: call gemini_service.explain(query, mode, lang)
    return {"query": query, "mode": mode, "lang": lang, "explanation": "", "disclaimer": DISCLAIMER}
