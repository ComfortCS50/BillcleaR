"""
Stage 1 ingestion pipeline: download each hospital's MRF from
data/hospitals.json, normalize it into the hospital_prices schema, and
insert it via app.services.db_service (stubbed -- counts rows without
persisting -- until DATABASE_URL is set in .env).

Usage:
    python scripts/ingest_mrfs.py
    python scripts/ingest_mrfs.py --hospital-id texas-childrens-main --hospital-id md-anderson
    python scripts/ingest_mrfs.py --limit-rows 20 --sample-size 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Hospital names/descriptions can contain characters (en-dashes, stray BOMs)
# that the default Windows console codepage can't encode -- widen stdout so a
# print() never crashes the run over a display-only issue.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.services import db_service
from app.services.ingestion.csv_parser import parse_csv
from app.services.ingestion.downloader import download_mrf
from app.services.ingestion.json_parser import parse_json

HOSPITALS_PATH = Path(__file__).resolve().parents[1] / "data" / "hospitals.json"
INSERT_BATCH_SIZE = 5000


def load_hospitals() -> list[dict]:
    return json.loads(HOSPITALS_PATH.read_text(encoding="utf-8"))


def ingest_hospital(hospital: dict, sample_size: int, limit_rows: int | None, force_download: bool) -> int:
    hospital_id = hospital["hospital_id"]
    print(f"=== {hospital_id} :: {hospital['name']} ===")

    path, fmt = download_mrf(hospital, force=force_download)
    declared = hospital.get("mrf_format")
    flag = "" if fmt == declared or (declared == "zip" and fmt in ("csv", "json")) else "  <-- declared mrf_format was wrong!"
    print(f"  file: {path.name} | detected format: {fmt} (declared: {declared}){flag}")

    if fmt == "csv":
        rows = parse_csv(path, hospital_id, hospital["name"])
    elif fmt == "json":
        rows = parse_json(path, hospital_id, hospital["name"])
    else:
        print(f"  SKIPPED: unsupported detected format {fmt!r}")
        return 0

    count = 0
    sample: list[dict] = []
    batch: list[dict] = []
    inserted = 0

    for row in rows:
        if limit_rows is not None and count >= limit_rows:
            break
        count += 1
        if len(sample) < sample_size:
            sample.append(row)
        batch.append(row)
        if len(batch) >= INSERT_BATCH_SIZE:
            inserted += db_service.insert_hospital_prices(batch)
            batch = []

    if batch:
        inserted += db_service.insert_hospital_prices(batch)

    print(f"  parsed {count} normalized row(s){' (limited)' if limit_rows is not None else ''}; sample:")
    for row in sample:
        print(f"    {row}")
    print(f"  db insert (or stub) count: {inserted}\n")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hospital-id", action="append", dest="hospital_ids", help="only ingest this hospital_id (repeatable)")
    parser.add_argument("--limit-rows", type=int, default=None, help="stop after N parsed rows per hospital (smoke testing)")
    parser.add_argument("--sample-size", type=int, default=5, help="how many normalized rows to print per hospital")
    parser.add_argument("--force-download", action="store_true", help="ignore the local cache in data/mrf_cache/")
    args = parser.parse_args()

    hospitals = load_hospitals()
    if args.hospital_ids:
        wanted = set(args.hospital_ids)
        hospitals = [h for h in hospitals if h["hospital_id"] in wanted]
        missing = wanted - {h["hospital_id"] for h in hospitals}
        if missing:
            print(f"WARNING: unknown hospital_id(s): {sorted(missing)}")

    if not db_service.DATABASE_URL:
        print("DATABASE_URL not set in .env -- DB insert is stubbed: rows are parsed and counted, not persisted.\n")

    grand_total = 0
    failures = []
    for hospital in hospitals:
        try:
            grand_total += ingest_hospital(
                hospital,
                sample_size=args.sample_size,
                limit_rows=args.limit_rows,
                force_download=args.force_download,
            )
        except Exception as exc:  # keep going across hospitals so one bad file doesn't kill the run
            print(f"  FAILED: {exc}\n")
            failures.append(hospital["hospital_id"])

    print(f"Done. {grand_total} total normalized row(s) across {len(hospitals) - len(failures)}/{len(hospitals)} hospital(s).")
    if failures:
        print(f"Failed: {failures}")


if __name__ == "__main__":
    main()
