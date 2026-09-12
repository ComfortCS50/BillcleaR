"""
Agentic orchestration layer.

Instead of the frontend calling /api/hospital, /api/bill, /api/explain
separately, this exposes ONE entry point (see app/routes/agent.py) where
Gemini itself decides which tool(s) to call and in what order, based on
what the user asked / uploaded.

Example flows this enables without extra routing logic on your end:
- User uploads a bill -> agent calls `extract_bill_line_items`, then for
  each line item calls `lookup_hospital_price` and `explain_term`, then
  writes one combined plain-language answer.
- User just asks "what does lisinopril do?" -> agent calls `explain_term`
  only, skips the other tools entirely.

This is Gemini "function calling" / tool use, not a separate framework —
no new dependency beyond the Gemini SDK you already have in
requirements.txt.

IMPORTANT: the exact call syntax for function calling has changed across
google-genai SDK versions. The TOOL_DECLARATIONS and dispatch table below
are stable regardless of SDK version — confirm the exact request/response
handling against the current docs at https://ai.google.dev/gemini-api/docs/function-calling
before wiring `run_agent()` for real (or hand this file + that link to
Claude Code and have it fill in the TODO).
"""

from app.services import db_service, gemini_service

# ---------------------------------------------------------------------------
# 1. Tool declarations — plain JSON-schema-style dicts, passed to Gemini so
#    it knows what tools exist and what arguments each one takes.
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS = [
    {
        "name": "extract_bill_line_items",
        "description": (
            "Extract structured line items (code, description, charge) from "
            "a photo or PDF of a hospital bill that the user uploaded."
        ),
        "parameters": {
            "type": "object",
            "properties": {},  # file bytes are passed separately, not as a Gemini arg
        },
    },
    {
        "name": "lookup_hospital_price",
        "description": (
            "Look up what a hospital's own posted price-transparency file "
            "says for a given procedure code or description, so it can be "
            "compared against what the patient was actually charged."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hospital_id": {"type": "string"},
                "procedure": {"type": "string", "description": "CPT/HCPCS code or plain description"},
            },
            "required": ["hospital_id", "procedure"],
        },
    },
    {
        "name": "explain_term",
        "description": (
            "Explain a medical procedure, medication, or billing code in "
            "plain language, including side effects for medications."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string"},
                "mode": {"type": "string", "enum": ["patient", "doctor"]},
                "lang": {"type": "string", "description": "e.g. 'en', 'es'"},
            },
            "required": ["term"],
        },
    },
]

# ---------------------------------------------------------------------------
# 2. Dispatch table — maps a tool name to the real Python function that
#    actually does the work (your existing service functions).
# ---------------------------------------------------------------------------

def _dispatch(tool_name: str, args: dict, file_bytes: bytes | None = None, mime_type: str | None = None):
    if tool_name == "extract_bill_line_items":
        return gemini_service.extract_bill_line_items(file_bytes, mime_type)
    if tool_name == "lookup_hospital_price":
        return db_service.get_prices(args["hospital_id"], args["procedure"])
    if tool_name == "explain_term":
        return gemini_service.explain(args["term"], args.get("mode", "patient"), args.get("lang", "en"))
    raise ValueError(f"Unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# 3. The agent loop.
#
# TODO (confirm exact SDK syntax against current Gemini function-calling
# docs before relying on this):
#   1. Send `user_message` (+ file, if any) and TOOL_DECLARATIONS to Gemini.
#   2. If the response contains a function_call part:
#        - run _dispatch(name, args, file_bytes, mime_type)
#        - send the result back to Gemini as a function_response part
#        - repeat (cap at MAX_STEPS so a bad loop can't run forever)
#   3. Once Gemini returns plain text (no more function_call parts),
#      return that as the final answer.
# ---------------------------------------------------------------------------

MAX_STEPS = 5


def run_agent(user_message: str, file_bytes: bytes | None = None, mime_type: str | None = None) -> dict:
    """
    Returns something like:
        {
            "answer": "...",
            "tool_calls": ["extract_bill_line_items", "lookup_hospital_price", ...],
        }
    `tool_calls` is worth surfacing in the UI/demo — it's the visible proof
    the agent (not a hardcoded if/else) decided the sequence.
    """
    raise NotImplementedError(
        "Wire this up against the current Gemini function-calling API. "
        "TOOL_DECLARATIONS and _dispatch() above are ready to use as-is."
    )
