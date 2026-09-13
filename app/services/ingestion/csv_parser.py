"""
Parses a CMS-standard hospital price transparency CSV (v3.0.0) and normalizes
it into the hospital_prices schema, regardless of whether the file uses the
"tall" (one row per code+payer) or "wide" (one row per code, payers exploded
into columns) layout.

Confirmed by hand against real files (see stage1-claude-code-brief.md):
- Every file has a 3-row preamble: row 1 = metadata headers, row 2 = metadata
  values, row 3 = the real pricing table header. Data starts at row 4.
- Tall layout has a `payer_name` column; wide layout does not.
- Both layouts provide `standard_charge|min` / `standard_charge|max` directly
  -- already aggregated by the hospital, never recomputed here.
- Which `code|N` slot holds the clinically useful code (CPT/HCPCS/MS-DRG...)
  vs. an internal chargemaster code varies by hospital, so the code is picked
  by scanning all code|N|type columns for a preferred billing code type.
- In the tall layout, one *item* (a given code+description+setting) repeats
  once per payer row, with gross/cash/min/max identical across every repeat --
  those columns are already hospital-aggregated, not payer-specific. Repeats
  are NOT necessarily adjacent in the file (verified: the same item's payer
  rows can be scattered rather than grouped together), so dedup tracks every
  key seen so far rather than only comparing to the previous row. Collapsing
  them to one row per item matches the granularity wide-layout and JSON files
  naturally produce.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

PREFERRED_CODE_TYPES = [
    "CPT", "HCPCS", "MS-DRG", "APC", "APR-DRG", "DRG", "NDC", "RC", "CDM",
]

# Columns that vary per payer row in the tall layout -- excluded when building
# the "is this the same item as the previous row" dedup key.
TALL_PAYER_VARYING_COLUMNS = {
    "payer_name", "plan_name", "modifiers",
    "standard_charge|negotiated_dollar",
    "standard_charge|negotiated_percentage",
    "standard_charge|negotiated_algorithm",
    "median_amount", "10th_percentile", "90th_percentile", "count",
    "standard_charge|methodology",
    "additional_payer_notes", "additional_generic_notes",
}


def _to_float(value) -> float | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pick_code(row: dict, fieldnames: list[str]) -> tuple[str, str]:
    slots = []
    i = 1
    while f"code|{i}" in fieldnames:
        code = (row.get(f"code|{i}") or "").strip()
        ctype = (row.get(f"code|{i}|type") or "").strip().upper()
        if code:
            slots.append((code, ctype))
        i += 1
    if not slots:
        return "", ""
    for preferred in PREFERRED_CODE_TYPES:
        for code, ctype in slots:
            if ctype == preferred:
                return code, ctype
    return slots[0]


def parse_csv(path: str | Path, hospital_id: str, hospital_name: str) -> Iterator[dict]:
    """
    Stream-parse a CMS-standard CSV file into normalized hospital_prices rows.
    Yields dicts, so a caller can consume the full file without loading it
    into memory.
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        preamble_reader = csv.reader(f)
        next(preamble_reader, None)  # row 1: metadata headers
        next(preamble_reader, None)  # row 2: metadata values
        header = next(preamble_reader, None)  # row 3: real pricing table header
        if header is None:
            return
        header = [h.strip() for h in header]

        is_tall = "payer_name" in header
        reader = csv.DictReader(f, fieldnames=header)

        seen_keys = set() if is_tall else None
        for row in reader:
            if not row or not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue

            if is_tall:
                key = tuple(
                    sorted(
                        (k, v) for k, v in row.items()
                        if k not in TALL_PAYER_VARYING_COLUMNS and k is not None
                    )
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)

            description = (row.get("description") or "").strip()
            code, _ctype = _pick_code(row, header)

            yield {
                "hospital_id": hospital_id,
                "hospital_name": hospital_name,
                "code": code,
                "description": description,
                "gross_charge": _to_float(row.get("standard_charge|gross")),
                "cash_price": _to_float(row.get("standard_charge|discounted_cash")),
                "negotiated_min": _to_float(row.get("standard_charge|min")),
                "negotiated_max": _to_float(row.get("standard_charge|max")),
            }
