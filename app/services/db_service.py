"""
Wraps all Tiger Data / Postgres access in one place so the challenge usage
is easy for judges (and you) to find.

Normalized schema (Stage 1):
    hospital_prices(
        hospital_id      text,
        hospital_name    text,
        code             text,   -- CPT/HCPCS code
        description       text,  -- plain description you wrote (not verbatim AMA CPT text)
        gross_charge     numeric,
        cash_price       numeric,
        negotiated_min   numeric,
        negotiated_max   numeric
    )

TODO:
- connect() -> a SQLAlchemy engine using DATABASE_URL from .env
- search_hospitals(name: str) -> list[dict]
- get_prices(hospital_id: str, procedure: str) -> list[dict]
- load_mrf(hospital_id: str, path: str) -> None
    One-off ingestion script: read a hospital's MRF file (CSV/JSON per the
    CMS standard template), normalize it, and insert into hospital_prices.
"""

import os

DATABASE_URL = os.getenv("DATABASE_URL")


def connect():
    raise NotImplementedError


def search_hospitals(name: str) -> list[dict]:
    raise NotImplementedError


def get_prices(hospital_id: str, procedure: str) -> list[dict]:
    raise NotImplementedError
