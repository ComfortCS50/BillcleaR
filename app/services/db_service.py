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

insert_hospital_prices() is stubbed (counts rows but doesn't persist) until
DATABASE_URL is set in .env -- see app/services/ingestion/ and
scripts/ingest_mrfs.py for the parsing pipeline that feeds it.
"""

import os
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

_engine = None
_pg_conn = None
_schema_ready = False

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hospital_prices (
    hospital_id     text    NOT NULL,
    hospital_name   text    NOT NULL,
    code            text,
    description     text,
    gross_charge    numeric,
    cash_price      numeric,
    negotiated_min  numeric,
    negotiated_max  numeric
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_hospital_prices_hospital_code
    ON hospital_prices (hospital_id, code);
"""

INSERT_COLUMNS = (
    "hospital_id", "hospital_name", "code", "description",
    "gross_charge", "cash_price", "negotiated_min", "negotiated_max",
)


def _normalized_dsn() -> str:
    # SQLAlchemy 1.4+ dropped the bare "postgres://" dialect alias that
    # Heroku/Tiger-style connection strings still use -- normalize it.
    if DATABASE_URL.startswith("postgres://"):
        return "postgresql://" + DATABASE_URL[len("postgres://"):]
    return DATABASE_URL


def connect():
    """SQLAlchemy engine, used for the light read queries below."""
    global _engine
    if not DATABASE_URL:
        raise NotImplementedError("DATABASE_URL is not set -- no Tiger Data/Postgres instance configured yet.")
    if _engine is None:
        from sqlalchemy import create_engine
        _engine = create_engine(_normalized_dsn())
    return _engine


def _pg_connection():
    """
    Raw psycopg2 connection used only for bulk inserts.

    SQLAlchemy's text()+executemany falls back to psycopg2's default
    executemany, which sends one INSERT per row -- against a remote Tiger
    Data instance that was measured at ~20,000 rows per 15 minutes (one
    network round trip per row). psycopg2.extras.execute_values rewrites a
    batch into a single multi-row INSERT statement instead.
    """
    global _pg_conn
    if not DATABASE_URL:
        raise NotImplementedError("DATABASE_URL is not set -- no Tiger Data/Postgres instance configured yet.")
    if _pg_conn is None or _pg_conn.closed:
        import psycopg2
        _pg_conn = psycopg2.connect(_normalized_dsn())
    return _pg_conn


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
        cur.execute(CREATE_INDEX_SQL)
    conn.commit()
    _schema_ready = True


def reset_hospital_prices() -> None:
    """Drop all rows (used to clear a partial/incomplete ingestion run)."""
    if not DATABASE_URL:
        return
    conn = _pg_connection()
    _ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE hospital_prices;")
    conn.commit()


def insert_hospital_prices(rows: Iterable[dict]) -> int:
    """
    Bulk-insert normalized rows into hospital_prices via a single multi-row
    INSERT per batch (psycopg2.extras.execute_values).

    Stubbed when DATABASE_URL isn't configured: rows are counted but not
    persisted, so the parsing pipeline can be developed and verified before
    Tiger Data is provisioned.
    """
    rows = list(rows)
    if not rows:
        return 0

    if not DATABASE_URL:
        print(f"[db_service] DATABASE_URL not set -- stubbing insert of {len(rows)} row(s) (not persisted).")
        return len(rows)

    import psycopg2.extras

    conn = _pg_connection()
    _ensure_schema(conn)
    values = [tuple(row.get(col) for col in INSERT_COLUMNS) for row in rows]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO hospital_prices ({', '.join(INSERT_COLUMNS)}) VALUES %s",
            values,
            page_size=2000,
        )
    conn.commit()
    return len(rows)


def _to_jsonable(row: dict) -> dict:
    for key in ("gross_charge", "cash_price", "negotiated_min", "negotiated_max"):
        if row.get(key) is not None:
            row[key] = float(row[key])
    return row


def search_hospitals(name: str) -> list[dict]:
    engine = connect()
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT DISTINCT hospital_id, hospital_name FROM hospital_prices WHERE hospital_name ILIKE :pattern"),
            {"pattern": f"%{name}%"},
        )
        return [dict(row._mapping) for row in result]


def get_prices(hospital_id: str, procedure: str) -> list[dict]:
    engine = connect()
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT hospital_id, hospital_name, code, description, gross_charge, cash_price, negotiated_min, negotiated_max
                FROM hospital_prices
                WHERE hospital_id = :hospital_id
                  AND (code = :procedure OR description ILIKE :pattern)
                """
            ),
            {"hospital_id": hospital_id, "procedure": procedure, "pattern": f"%{procedure}%"},
        )
        return [_to_jsonable(dict(row._mapping)) for row in result]
