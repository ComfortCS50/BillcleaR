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

GEMINI_MODEL defaults to "gemini-3.6-flash", picked by live-testing against
the real key rather than guessing a name from memory: "gemini-flash-latest"
(self-updating alias) hit repeated 503 UNAVAILABLE ("high demand") errors --
client.models.list() confirmed "-latest" is Google's lower-quota
experimental alias. Fell back to "gemini-2.5-flash" (a GA, non-preview
model) but that returned 404 NOT_FOUND: "no longer available to new users
... use models/gemini-3.6-flash" -- so that's what's pinned here. Override
via GEMINI_MODEL in .env if needed.
"""

import json
import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

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
    gross = hospital_prices.get("hospital_gross_charge")
    cash = hospital_prices.get("hospital_cash_price")
    lo = hospital_prices.get("hospital_negotiated_min")
    hi = hospital_prices.get("hospital_negotiated_max")

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


NEGOTIATION_PLAN_PROMPT = """\
You are helping a patient prepare to negotiate a hospital bill down, using
real price-transparency data from that same hospital's own posted files.
You will receive a JSON object summarizing the total billed amount for the
line items that could be matched against the hospital's price file, and
what that file says (gross charge, cash/self-pay price, negotiated rate
range) for those same items.

Return ONLY a JSON object (no markdown fences, no commentary, no
surrounding text) with exactly these keys:
  - "target_amount": a single plain number (no "$" or commas) the patient
    should ask to pay. Prefer the hospital's own cash/self-pay price when
    it's provided; otherwise use the low end of the negotiated range.
    Never suggest a number higher than what the patient was actually
    billed for those items. If nothing in the data supports a specific
    number, set this to null.
  - "target_rationale": one sentence explaining why that number is
    defensible -- it should reference that this comes from the hospital's
    own federally-required price transparency file, not a guess. If
    target_amount is null, explain briefly why no specific number could
    be determined instead.
  - "script": 3-5 sentences the patient could read close to verbatim on a
    phone call with the hospital's billing department, calmly requesting
    the self-pay/cash rate (or negotiated rate) found in the hospital's
    own file. Plain language, non-confrontational, something a layperson
    would actually say out loud -- not legal or technical phrasing.
  - "financial_assistance_reminder": one sentence reminding the patient to
    also ask the billing department about financial assistance or charity
    care eligibility if paying this bill would be a hardship, especially
    since many hospitals (particularly nonprofits) offer this.
"""


def generate_negotiation_plan(comparison_summary: dict) -> dict | None:
    """
    One Gemini call, made once per bill upload (not per line item) after
    line items have been translated and compared against hospital price
    data. Produces a structured, linear "negotiation plan": a concrete
    target number, a phone script, and a financial-assistance reminder.

    `comparison_summary` should look like:
        {
            "total_billed": float,
            "hospital_gross_total": float | None,
            "hospital_cash_total": float | None,
            "hospital_negotiated_min_total": float | None,
            "hospital_negotiated_max_total": float | None,
            "matched_item_count": int,
            "total_item_count": int,
        }

    Returns None (rather than raising) if Gemini's response isn't valid
    JSON -- the caller should treat a missing plan as "couldn't generate
    one this time" and simply not render that section.
    """
    from google.genai import types

    client = get_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=json.dumps(comparison_summary),
        config=types.GenerateContentConfig(
            system_instruction=NEGOTIATION_PLAN_PROMPT,
            response_mime_type="application/json",
        ),
    )

    try:
        plan = json.loads(response.text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(plan, dict):
        return None
    return plan
