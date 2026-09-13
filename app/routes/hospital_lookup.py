"""
Stage 2 — Hospital + procedure price lookup, backed by the real rows loaded
into Tiger Data by scripts/ingest_mrfs.py.

- GET /api/hospital/search?name=... -> hospitals we have loaded matching `name`
- GET /api/hospital/{hospital_id}/prices?procedure=... -> gross/cash/negotiated
  rate comparison for that procedure at that hospital
"""

from fastapi import APIRouter, HTTPException

from app.services import db_service

router = APIRouter()

# Static note, not a real-time eligibility calculation -- most patients
# simply don't know this option exists, so it's worth always surfacing
# alongside a price comparison.
FINANCIAL_ASSISTANCE_NOTE = (
    "Many hospitals, especially nonprofits, offer financial assistance or "
    "charity care. Ask the hospital's billing department for a financial "
    "counselor or an ability-to-pay application."
)


@router.get("/search")
def search_hospitals(name: str = ""):
    try:
        results = db_service.search_hospitals(name)
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"query": name, "results": results}


@router.get("/{hospital_id}/prices")
def get_prices(hospital_id: str, procedure: str = ""):
    try:
        rows = db_service.get_prices(hospital_id, procedure)
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    summary = None
    if rows:
        gross = [r["gross_charge"] for r in rows if r["gross_charge"] is not None]
        cash = [r["cash_price"] for r in rows if r["cash_price"] is not None]
        mins = [r["negotiated_min"] for r in rows if r["negotiated_min"] is not None]
        maxs = [r["negotiated_max"] for r in rows if r["negotiated_max"] is not None]
        summary = {
            "match_count": len(rows),
            "gross_charge_range": [min(gross), max(gross)] if gross else None,
            "cash_price_range": [min(cash), max(cash)] if cash else None,
            "negotiated_min": min(mins) if mins else None,
            "negotiated_max": max(maxs) if maxs else None,
        }

    return {
        "hospital_id": hospital_id,
        "procedure": procedure,
        "prices": rows,
        "summary": summary,
        "financial_assistance_note": FINANCIAL_ASSISTANCE_NOTE,
    }
