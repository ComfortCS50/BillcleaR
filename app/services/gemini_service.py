"""
Wraps all Gemini API calls in one place so the challenge usage is easy
for judges (and you) to find.

TODO:
- extract_bill_line_items(file_bytes, mime_type) -> list[dict]
    Send the bill image/PDF to Gemini with a prompt asking for structured
    JSON output: [{code, description, charge}, ...]
- explain(query, mode="patient", lang="en") -> str
    Ask Gemini to explain a procedure/medication/line-item in plain language.
    `mode` controls patient vs. clinical phrasing; `lang` controls output language.
- narrate_price_gap(charge, hospital_prices) -> str
    Given what the patient was billed vs. the hospital's own posted prices,
    have Gemini narrate the comparison in plain language.
"""

import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def extract_bill_line_items(file_bytes: bytes, mime_type: str) -> list[dict]:
    raise NotImplementedError


def explain(query: str, mode: str = "patient", lang: str = "en") -> str:
    raise NotImplementedError


def narrate_price_gap(charge: float, hospital_prices: dict) -> str:
    raise NotImplementedError
