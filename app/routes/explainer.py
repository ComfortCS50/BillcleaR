"""
Stage 4 — Procedure / medication explainer.

GET /api/explain?query=...&mode=patient|doctor&lang=en

Always includes a "not medical advice" disclaimer in the response payload
itself (not just the frontend), so any API caller sees it.
"""

from fastapi import APIRouter, HTTPException
from google.genai.errors import APIError

from app.services import gemini_service

router = APIRouter()

DISCLAIMER = "This is general information, not medical advice."


@router.get("")
def explain(query: str, mode: str = "patient", lang: str = "en"):
    if mode not in ("patient", "doctor"):
        mode = "patient"
    try:
        explanation = gemini_service.explain(query, mode, lang)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}")
    return {"query": query, "mode": mode, "lang": lang, "explanation": explanation, "disclaimer": DISCLAIMER}
