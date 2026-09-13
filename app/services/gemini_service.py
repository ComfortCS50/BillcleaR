"""
Wraps all Gemini API calls in one place so the challenge usage is easy
for judges (and you) to find.

Built against the installed google-genai SDK (2.23.0, introspected directly
rather than assumed from memory/docs, since the exact call surface shifts
between versions -- see stage2-4-claude-code-brief.md). Uses the stable,
fully-typed `client.models.generate_content()` API rather than the newer
`client.interactions` API: the latter's Python signature is an untyped
`**body`, which can't be verified without a live API key, and there wasn't
one available at build time (GEMINI_API_KEY in .env is still the
placeholder value) -- generate_content is the safer bet for a judged demo.

GEMINI_MODEL defaults to the "gemini-flash-latest" alias (self-updating,
avoids hardcoding a dated version string that may get deprecated) -- pin a
specific version in .env once you've confirmed what's enabled for your key
via `client.models.list()`.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

_client = None


def _is_configured() -> bool:
    return bool(GEMINI_API_KEY) and GEMINI_API_KEY != "your-gemini-api-key-here"


def get_client():
    """
    Shared client, reused by gemini_service and agent_service so both hit
    the same configured model/key.
    """
    global _client
    if not _is_configured():
        raise RuntimeError(
            "GEMINI_API_KEY is not set in .env (still the placeholder value) -- "
            "Gemini-backed features are unavailable until a real key is added."
        )
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


BILL_EXTRACTION_PROMPT = """\
You are extracting line items from a photo or PDF of a hospital bill.

Return ONLY a JSON array (no markdown fences, no commentary, no surrounding
text). Each element must be an object with exactly these keys:
  - "code": the billing code printed on the bill (CPT/HCPCS/revenue code/etc), \
or null if none is printed for that line
  - "description": the line item's description exactly as printed
  - "charge": the dollar amount charged for that line, as a plain number \
(no "$" or commas), or null if it can't be determined

Only extract line items that are actually itemized charges -- skip totals,
subtotals, payment/adjustment lines, and headers. Do not invent codes or
descriptions that aren't printed on the bill.
"""

EXPLAIN_SYSTEM_PROMPTS = {
    "patient": (
        "You are explaining a medical procedure, medication, or billing term "
        "to a patient with no medical background. Use plain language and short "
        "sentences, avoid jargon (or define it immediately if you must use it). "
        "If the term is a medication, always mention common side effects. "
        "Keep the whole answer under ~150 words."
    ),
    "doctor": (
        "You are giving a clinical explanation to a healthcare-literate reader "
        "(e.g. a physician, nurse, or medical coder). Standard clinical "
        "terminology is fine. For a medication, include mechanism of action, "
        "primary indication, and clinically relevant side effects/"
        "contraindications. For a procedure or billing code, include what it "
        "covers and typical clinical context."
    ),
}


def extract_bill_line_items(file_bytes: bytes, mime_type: str) -> list[dict]:
    """
    Send a bill image/PDF to Gemini and return [{code, description, charge}, ...].
    Returns [] if Gemini's response isn't valid JSON or isn't a list, rather
    than raising, so a single bad extraction doesn't 500 the whole request.
    """
    from google.genai import types

    client = get_client()
    part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[part],
        config=types.GenerateContentConfig(
            system_instruction=BILL_EXTRACTION_PROMPT,
            response_mime_type="application/json",
        ),
    )

    try:
        items = json.loads(response.text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def explain(query: str, mode: str = "patient", lang: str = "en") -> str:
    """
    Plain-language (patient) or clinical (doctor) explanation of a procedure,
    medication, or billing term. Reused by both the standalone explainer
    (Stage 4) and bill line-item translation (Stage 3) -- same prompt logic,
    not duplicated.
    """
    from google.genai import types

    client = get_client()
    system_prompt = EXPLAIN_SYSTEM_PROMPTS.get(mode, EXPLAIN_SYSTEM_PROMPTS["patient"])
    if lang and lang != "en":
        system_prompt += f" Respond in the language with code '{lang}'."

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=query,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return (response.text or "").strip()


def narrate_price_gap(charge: float, hospital_prices: dict) -> str:
    """
    Plain-language comparison of what a patient was billed vs. what the
    hospital's own posted price-transparency file says for that item.

    Deterministic (no Gemini call): this is just arithmetic/formatting over
    numbers we already trust, so there's no reason to spend an API call or
    risk a hallucinated dollar figure on it.
    """
    gross = hospital_prices.get("gross_charge")
    cash = hospital_prices.get("cash_price")
    lo = hospital_prices.get("negotiated_min")
    hi = hospital_prices.get("negotiated_max")

    if charge is None or (lo is None and hi is None and gross is None):
        return "No comparable hospital-posted price was found for this line item."

    parts = [f"You were charged ${charge:,.2f}."]
    if lo is not None and hi is not None:
        parts.append(f"This hospital's own negotiated rates for this item range from ${lo:,.2f} to ${hi:,.2f}.")
        if charge > hi:
            parts.append("The billed amount is above the top of that negotiated range.")
        elif charge < lo:
            parts.append("The billed amount is below the bottom of that negotiated range.")
        else:
            parts.append("The billed amount falls within that negotiated range.")
    if gross is not None:
        parts.append(f"The hospital's posted (undiscounted) gross charge for this item is ${gross:,.2f}.")
    if cash is not None:
        parts.append(f"Its cash-pay discounted price is ${cash:,.2f}.")
    return " ".join(parts)
