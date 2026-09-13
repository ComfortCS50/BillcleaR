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
# Built against the installed google-genai SDK (2.23.0), verified by directly
# introspecting types.FunctionDeclaration / types.Tool / types.Part /
# types.FunctionResponse offline rather than trusting docs/memory (the exact
# call surface shifts between SDK versions). Uses the same stable
# `generate_content` API as gemini_service.py, not the newer `interactions`
# API -- see that module's docstring for why.
# ---------------------------------------------------------------------------

MAX_STEPS = 5

AGENT_SYSTEM_INSTRUCTION = (
    "You are BillClear's assistant. You help patients understand a hospital "
    "bill they uploaded, look up what a hospital's own posted prices say "
    "about a procedure, and explain medical procedures/medications in plain "
    "language. Use the available tools rather than answering from your own "
    "knowledge when a tool applies -- e.g. always call lookup_hospital_price "
    "before claiming what a hospital charges, and always call "
    "extract_bill_line_items first if the user uploaded a bill. Once you "
    "have what you need from tools, give one clear final answer in plain "
    "language, and always note this is general information, not medical "
    "or legal advice."
)


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
    from google.genai import types

    client = gemini_service.get_client()
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(**decl) for decl in TOOL_DECLARATIONS])
    config = types.GenerateContentConfig(system_instruction=AGENT_SYSTEM_INSTRUCTION, tools=[tool])

    parts = []
    if file_bytes:
        parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type or "application/octet-stream"))
    parts.append(types.Part(text=user_message))
    contents = [types.Content(role="user", parts=parts)]

    tool_calls_log: list[str] = []

    for _ in range(MAX_STEPS):
        response = client.models.generate_content(model=gemini_service.GEMINI_MODEL, contents=contents, config=config)
        calls = response.function_calls or []
        if not calls:
            return {"answer": (response.text or "").strip(), "tool_calls": tool_calls_log}

        contents.append(response.candidates[0].content)

        response_parts = []
        for call in calls:
            tool_calls_log.append(call.name)
            try:
                result = _dispatch(call.name, dict(call.args or {}), file_bytes, mime_type)
            except Exception as exc:  # surface the failure to Gemini so it can recover/apologize instead of crashing the request
                result = {"error": str(exc)}
            response_parts.append(types.Part(function_response=types.FunctionResponse(name=call.name, response={"result": result})))
        contents.append(types.Content(role="user", parts=response_parts))

    return {
        "answer": "Reached the max number of tool-call steps without a final answer. Please try rephrasing your question.",
        "tool_calls": tool_calls_log,
    }
