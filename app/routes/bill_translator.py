"""
Stage 3 — Bill upload & translate.

TODO:
- POST /api/bill/upload -> accept a photo/PDF of a bill
- Send directly to Gemini (multimodal) asking for structured JSON:
  line items, codes, descriptions, charges. See app/services/gemini_service.py
- Cross-reference extracted codes against the hospital's price data (Stage 2)
  if it's a hospital we have loaded.
- Feed each line item back to Gemini for a plain-language explanation.
"""

from fastapi import APIRouter, UploadFile, File

router = APIRouter()


@router.post("/upload")
async def upload_bill(file: UploadFile = File(...)):
    # TODO: pass file bytes to gemini_service.extract_bill_line_items()
    contents = await file.read()
    return {"filename": file.filename, "size_bytes": len(contents), "line_items": []}
