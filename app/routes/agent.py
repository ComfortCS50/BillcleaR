"""
Single conversational entry point. The frontend can call this instead of
hitting /api/hospital, /api/bill, /api/explain separately — the agent
decides which of those tools it needs based on the message (+ optional
uploaded file).

Keep the three separate routers too (hospital_lookup, bill_translator,
explainer) — they're useful for direct testing/demo of each piece even
after the agent is wired up, and give you a fallback if the agent loop
has issues during your live demo.
"""

from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional

from app.services.agent_service import run_agent

router = APIRouter()


@router.post("")
async def ask_agent(message: str = Form(...), file: Optional[UploadFile] = File(None)):
    file_bytes = await file.read() if file else None
    mime_type = file.content_type if file else None
    return run_agent(message, file_bytes, mime_type)
