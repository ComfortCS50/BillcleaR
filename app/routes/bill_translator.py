"""
Stage 3 — Bill upload & translate (headline feature).

POST /api/bill/upload
  multipart form: file (image/PDF), optional hospital_id, optional lang

For each line item Gemini extracts from the bill:
- cross-reference against loaded hospital price data (Stage 2's
  db_service.get_prices()) when hospital_id is one we have loaded
- translate the line item to plain language via gemini_service.explain()
  (Stage 4's function, reused as-is -- no duplicate prompt logic)
"""

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.genai.errors import APIError

from app.services import db_service, gemini_service

router = APIRouter()


def _price_match(hospital_id: str, code, description: str) -> Optional[dict]:
    lookup_term = (code or description or "").strip()
    if not lookup_term:
        return None
    try:
        rows = db_service.get_prices(hospital_id, lookup_term)
    except NotImplementedError:
        return None
    if not rows:
        return None

    mins = [r["negotiated_min"] for r in rows if r["negotiated_min"] is not None]
    maxs = [r["negotiated_max"] for r in rows if r["negotiated_max"] is not None]
    return {
        "match_count": len(rows),
        "hospital_gross_charge": rows[0]["gross_charge"],
        "hospital_cash_price": rows[0]["cash_price"],
        "hospital_negotiated_min": min(mins) if mins else None,
        "hospital_negotiated_max": max(maxs) if maxs else None,
    }


@router.post("/upload")
async def upload_bill(
    file: UploadFile = File(...),
    hospital_id: Optional[str] = Form(None),
    lang: str = Form("en"),
):
    contents = await file.read()
    mime_type = file.content_type or "application/octet-stream"

    try:
        raw_items = gemini_service.extract_bill_line_items(contents, mime_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except APIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}")

    line_items = []
    for item in raw_items:
        code = item.get("code")
        description = (item.get("description") or "").strip()
        charge = item.get("charge")

        price_comparison = _price_match(hospital_id, code, description) if hospital_id else None

        explanation = ""
        price_narrative = ""
        if description:
            try:
                explanation = gemini_service.explain(description, mode="patient", lang=lang)
            except (RuntimeError, APIError):
                explanation = ""  # don't let one bad line item's explanation abort the whole bill
            if price_comparison and charge is not None:
                price_narrative = gemini_service.narrate_price_gap(charge, price_comparison)

        line_items.append({
            "code": code,
            "description": description,
            "charge": charge,
            "explanation": explanation,
            "hospital_price_comparison": price_comparison,
            "price_narrative": price_narrative,
        })

    return {
        "filename": file.filename,
        "hospital_id": hospital_id,
        "line_items": line_items,
        "disclaimer": "This is general information, not medical or billing advice.",
    }
