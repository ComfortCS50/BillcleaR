"""
Parses the CommonSpirit (Baylor St. Luke's / St. Luke's Woodlands / Vintage /
Sugar Land) CMS-standard JSON MRF and normalizes it into the hospital_prices
schema.

Structure confirmed by fetching the real Baylor St. Luke's file (256MB) and
inspecting it directly -- not assumed from the CMS spec:

    {
      "hospital_name": ...,
      "standard_charge_information": [
        {
          "description": "...",
          "code_information": [{"code": "...", "type": "CPT"|"MS-DRG"|"RC"|...}, ...],
          "standard_charges": [
            {
              "minimum": ..., "maximum": ...,
              "gross_charge": ...,       # not present on every entry
              "discounted_cash": ...,    # not present on every entry
              "setting": "inpatient"|"outpatient",
              "payers_information": [{"payer_name", "plan_name", "standard_charge_dollar", ...}, ...]
            },
            ...  # one entry per setting/charge basis for this item
          ]
        },
        ...
      ]
    }

Per-payer negotiated rates (payers_information) aren't part of the
hospital_prices schema, so they're not extracted here -- only the
hospital-aggregated minimum/maximum/gross/cash per standard_charges entry,
same granularity the CSV parser produces (one row per item per setting).

Files run into the hundreds of MB, so this streams with ijson instead of
json.load()'ing the whole file into memory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import ijson

PREFERRED_CODE_TYPES = [
    "CPT", "HCPCS", "MS-DRG", "APC", "APR-DRG", "DRG", "NDC", "RC", "CDM",
]


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pick_code(code_information: list[dict]) -> tuple[str, str]:
    slots = [
        ((c.get("code") or "").strip(), (c.get("type") or "").strip().upper())
        for c in code_information or []
        if c.get("code")
    ]
    if not slots:
        return "", ""
    for preferred in PREFERRED_CODE_TYPES:
        for code, ctype in slots:
            if ctype == preferred:
                return code, ctype
    return slots[0]


def parse_json(path: str | Path, hospital_id: str, hospital_name: str) -> Iterator[dict]:
    """
    Stream-parse a CMS-standard JSON MRF into normalized hospital_prices rows.
    """
    with open(path, "rb") as f:
        if f.read(3) != b"\xef\xbb\xbf":  # skip a leading UTF-8 BOM; ijson chokes on it
            f.seek(0)
        for item in ijson.items(f, "standard_charge_information.item"):
            description = (item.get("description") or "").strip()
            code, _ctype = _pick_code(item.get("code_information") or [])

            for charge in item.get("standard_charges") or []:
                yield {
                    "hospital_id": hospital_id,
                    "hospital_name": hospital_name,
                    "code": code,
                    "description": description,
                    "gross_charge": _to_float(charge.get("gross_charge")),
                    "cash_price": _to_float(charge.get("discounted_cash")),
                    "negotiated_min": _to_float(charge.get("minimum")),
                    "negotiated_max": _to_float(charge.get("maximum")),
                }
