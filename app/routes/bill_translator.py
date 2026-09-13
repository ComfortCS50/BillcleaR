"""
Stage 3 — Bill upload & translate (headline feature).

POST /api/bill/upload
  multipart form: file (image/PDF), optional hospital_id, optional lang

For each line item Gemini extracts from the bill:
- cross-reference against loaded hospital price data (Stage 2's
  db_service.get_prices()) when hospital_id is one we have loaded
- translate the line item to plain language via gemini_service.explain()
  (Stage 4's function, reused as-is -- no duplicate prompt logic)

Once every line item is translated and compared, one more Gemini call
(gemini_service.generate_negotiation_plan) turns the bill-level totals
into a concrete "negotiation plan": a target dollar amount, a phone
script, and a financial-assistance reminder -- the payoff of the whole
upload flow, not a per-line-item afterthought.
"""

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from google.genai.errors import APIError

from app.services import db_service, gemini_service

router = APIRouter()

# Static note, not a real-time eligibility calculation -- most patients
# simply don't know this option exists, so it's worth always surfacing.
FINANCIAL_ASSISTANCE_NOTE = (
    "Many hospitals, especially nonprofits, offer financial assistance or "
    "charity care. Ask the hospital's billing department for a financial "
    "counselor or an ability-to-pay application."
)


def _aggregate_price_comparison(line_items: list[dict]) -> dict:
    """
    Roll the per-line-item hospital_price_comparison entries up into one
    bill-level summary, feeding the single negotiation-plan Gemini call.
    Only items that actually matched hospital price data (and have a
    charge) count toward the totals -- an unmatched item has no grounds
    for a negotiation ask.
    """
    matched = [
        item for item in line_items
        if item.get("hospital_price_comparison") and item.get("charge") is not None
    ]
    gross_values = [m["hospital_price_comparison"]["hospital_gross_charge"] for m in matched if m["hospital_price_comparison"].get("hospital_gross_charge") is not None]
    cash_values = [m["hospital_price_comparison"]["hospital_cash_price"] for m in matched if m["hospital_price_comparison"].get("hospital_cash_price") is not None]
    min_values = [m["hospital_price_comparison"]["hospital_negotiated_min"] for m in matched if m["hospital_price_comparison"].get("hospital_negotiated_min") is not None]
    max_values = [m["hospital_price_comparison"]["hospital_negotiated_max"] for m in matched if m["hospital_price_comparison"].get("hospital_negotiated_max") is not None]

    return {
        "total_billed": sum(m["charge"] for m in matched) if matched else None,
        "hospital_gross_total": sum(gross_values) if gross_values else None,
        "hospital_cash_total": sum(cash_values) if cash_values else None,
        "hospital_negotiated_min_total": sum(min_values) if min_values else None,
        "hospital_negotiated_max_total": sum(max_values) if max_values else None,
        "matched_item_count": len(matched),
        "total_item_count": len(line_items),
    }


def _price_match(hospital_id: str, code, description: str) -> Optional[dict]:
    code = (code or "").strip() or None
    description = (description or "").strip() or None
    if not code and not description:
        return None
    try:
        rows = db_service.get_price_for_bill_item(hospital_id, code, description)
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

    negotiation_plan = None
    comparison_summary = _aggregate_price_comparison(line_items)
    if comparison_summary["matched_item_count"] > 0:
        try:
            negotiation_plan = gemini_service.generate_negotiation_plan(comparison_summary)
        except (RuntimeError, APIError):
            negotiation_plan = None  # bill translation still succeeds without the plan

    return {
        "filename": file.filename,
        "hospital_id": hospital_id,
        "line_items": line_items,
        "disclaimer": "This is general information, not medical or billing advice.",
        "financial_assistance_note": FINANCIAL_ASSISTANCE_NOTE,
        "negotiation_plan": negotiation_plan,
    }
