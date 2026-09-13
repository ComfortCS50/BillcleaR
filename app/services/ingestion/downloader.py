"""
Downloads a hospital's MRF file and hands back a local path plus its real
detected format.

`mrf_format` in data/hospitals.json is not reliable: Houston Methodist's two
entries declare "csv" but the URL (a .ashx endpoint with no extension) actually
serves raw CMS JSON. So instead of trusting the declared format, every
downloaded file is sniffed by its actual bytes (zip magic number / leading
`{`-`[` for JSON / otherwise CSV) and zip archives are extracted first.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import requests

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "mrf_cache"
USER_AGENT = "Mozilla/5.0 (billclear-ingestion/1.0)"


def sniff_format(head: bytes) -> str:
    """Inspect the first bytes of a file and return 'zip', 'json', or 'csv'."""
    stripped = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if stripped[:2] == b"PK":
        return "zip"
    if stripped[:1] in (b"{", b"["):
        return "json"
    return "csv"


def _download_raw(url: str, dest: Path) -> None:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=180, stream=True)
    resp.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    tmp.replace(dest)


def download_mrf(
    hospital: dict,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    force: bool = False,
) -> tuple[Path, str]:
    """
    Fetch (or reuse a cached copy of) a hospital's MRF, unzip it if it turns
    out to be a zip archive, and return (local_path, detected_format) where
    detected_format is "csv" or "json" based on the real file content.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    hospital_id = hospital["hospital_id"]
    url = hospital["mrf_url"]

    raw_path = cache_dir / f"{hospital_id}.download"
    if force or not raw_path.exists():
        _download_raw(url, raw_path)

    with open(raw_path, "rb") as f:
        head = f.read(4096)
    fmt = sniff_format(head)

    if fmt != "zip":
        return raw_path, fmt

    with zipfile.ZipFile(raw_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if len(members) != 1:
            raise ValueError(
                f"{hospital_id}: expected exactly one file inside the zip, found {members}"
            )
        inner_name = members[0]
        extracted_path = cache_dir / f"{hospital_id}__{Path(inner_name).name}"
        if force or not extracted_path.exists():
            with zf.open(inner_name) as src, open(extracted_path, "wb") as dst:
                for block in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(block)

    with open(extracted_path, "rb") as f:
        inner_head = f.read(4096)
    inner_fmt = sniff_format(inner_head)
    if inner_fmt == "zip":
        raise ValueError(f"{hospital_id}: nested zip not supported")

    return extracted_path, inner_fmt
