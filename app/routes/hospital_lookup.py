"""
Stage 2 — Hospital + procedure lookup.

TODO:
- Load normalized price data from Postgres/Tiger Data (see data/hospitals.json
  for the pre-vetted list of hospitals + their MRF source URLs).
- GET /api/hospital/search?name=... -> list of matching supported hospitals
- GET /api/hospital/{hospital_id}/prices?procedure=... -> gross/cash/negotiated
  rate comparison for that procedure at that hospital
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/search")
def search_hospitals(name: str = ""):
    # TODO: query Tiger Data for hospitals matching `name`
    return {"query": name, "results": []}


@router.get("/{hospital_id}/prices")
def get_prices(hospital_id: str, procedure: str = ""):
    # TODO: query normalized price table for this hospital + procedure code/description
    return {"hospital_id": hospital_id, "procedure": procedure, "prices": []}
