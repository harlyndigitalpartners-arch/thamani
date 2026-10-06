"""OCDS Data Ingestion and SQLite Caching for Thamani.

Downloads OCDS releases from the Open Contracting Partnership (OCP) Data Registry
(Kenya PPRA publication 147) and loads them into a fast, local SQLite database.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
)
logger = logging.getLogger("thamani.ocds")

DOWNLOAD_URL_TEMPLATE = "https://data.open-contracting.org/en/publication/147/download?name={year}.jsonl.gz"


def norm_name(name: str | None) -> str:
    """Normalize corporate supplier or buyer names.

    Strips punctuation, collapses whitespace, converts to uppercase,
    and removes corporate legal suffixes so variants like
    'AFRICAN TOUCH SAFARIS' and 'AFRICAN TOUCH SAFARIS LIMITED'
    normalize to the same identifier.
    """
    if not name:
        return ""
    s = str(name).strip().upper()
    # Remove punctuation characters
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Strip corporate entity suffixes
    for _ in range(2):
        s = re.sub(r"\b(LIMITED|LTD|COMPANY|CO|CORPORATION|CORP|INC|PLC)\b\s*$", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Initialize SQLite tables and indexes matching the data contract."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenders (
                ocid TEXT PRIMARY KEY,
                tender_id TEXT,
                title TEXT,
                procurement_method TEXT,
                category TEXT,
                buyer_id TEXT,
                buyer_name TEXT,
                record_date TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS awards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ocid TEXT,
                award_id TEXT,
                award_date TEXT,
                value_amount REAL,
                value_currency TEXT,
                supplier_id TEXT,
                supplier_name TEXT,
                supplier_name_norm TEXT,
                buyer_id TEXT,
                buyer_name TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_awards_ocid ON awards(ocid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_awards_supplier_norm ON awards(supplier_name_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_awards_buyer_id ON awards(buyer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_category ON tenders(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_awards_value ON awards(value_amount)")

    return conn


def download_year(year: int | str, data_dir: str | Path) -> Path:
    """Download a year's jsonl.gz archive from OCP registry if not present."""
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{year}.jsonl.gz"

    if target_file.exists() and target_file.stat().st_size > 0:
        logger.info(f"Using cached file: {target_file} ({target_file.stat().st_size:,} bytes)")
        return target_file

    url = DOWNLOAD_URL_TEMPLATE.format(year=year)
    logger.info(f"Downloading {url} -> {target_file} ...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ThamaniIngest/1.0"},
    )
    temp_file = target_dir / f"{year}.jsonl.gz.tmp"
    with urllib.request.urlopen(req) as resp, open(temp_file, "wb") as out:
        chunk_size = 1024 * 1024
        while chunk := resp.read(chunk_size):
            out.write(chunk)
    temp_file.replace(target_file)
    logger.info(f"Downloaded {target_file} ({target_file.stat().st_size:,} bytes)")
    return target_file


def ingest_file(file_path: Path, conn: sqlite3.Connection, batch_size: int = 5000) -> tuple[int, int]:
    """Ingest a single .jsonl.gz file into tenders and awards tables."""
    tenders_batch: list[tuple] = []
    awards_batch: list[tuple] = []
    tenders_count = 0
    awards_count = 0

    def flush_batches():
        nonlocal tenders_batch, awards_batch, tenders_count, awards_count
        if tenders_batch:
            conn.executemany("""
                INSERT OR REPLACE INTO tenders (
                    ocid, tender_id, title, procurement_method, category,
                    buyer_id, buyer_name, record_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, tenders_batch)
            tenders_count += len(tenders_batch)
            tenders_batch = []
        if awards_batch:
            conn.executemany("""
                INSERT INTO awards (
                    ocid, award_id, award_date, value_amount, value_currency,
                    supplier_id, supplier_name, supplier_name_norm, buyer_id, buyer_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, awards_batch)
            awards_count += len(awards_batch)
            awards_batch = []
        conn.commit()

    with gzip.open(file_path, "rt", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception as e:
                logger.warning(f"Failed to parse line {line_num} in {file_path.name}: {e}")
                continue

            # Support single release or package with releases
            releases = record.get("releases", [record]) if isinstance(record.get("releases"), list) else [record]

            for rel in releases:
                ocid = rel.get("ocid")
                if not ocid:
                    continue

                tender = rel.get("tender") or {}
                buyer = rel.get("buyer") or {}
                buyer_id = str(buyer.get("id") or "").strip()
                buyer_name = str(buyer.get("name") or "").strip()
                record_date = rel.get("date") or ""

                category = (
                    tender.get("mainProcurementCategory")
                    or tender.get("category")
                    or ""
                ).strip().lower()

                tender_id = str(tender.get("id") or "").strip()
                title = str(tender.get("title") or "").strip()
                proc_method = str(tender.get("procurementMethod") or "").strip()

                tenders_batch.append((
                    ocid,
                    tender_id,
                    title,
                    proc_method,
                    category,
                    buyer_id,
                    buyer_name,
                    record_date,
                ))

                rel_awards = rel.get("awards") or []
                for aw in rel_awards:
                    award_id = str(aw.get("id") or "").strip()
                    award_date = aw.get("date") or record_date
                    val = aw.get("value") or {}
                    val_amount = val.get("amount")
                    try:
                        value_amount = float(val_amount) if val_amount is not None else 0.0
                    except (ValueError, TypeError):
                        value_amount = 0.0
                    value_currency = str(val.get("currency") or "KES").strip().upper()

                    suppliers = aw.get("suppliers") or []
                    if not suppliers:
                        suppliers = [{"id": "", "name": ""}]

                    for sup in suppliers:
                        sup_id = str(sup.get("id") or "").strip()
                        sup_name = str(sup.get("name") or "").strip()
                        sup_norm = norm_name(sup_name)

                        awards_batch.append((
                            ocid,
                            award_id,
                            award_date,
                            value_amount,
                            value_currency,
                            sup_id,
                            sup_name,
                            sup_norm,
                            buyer_id,
                            buyer_name,
                        ))

            if len(tenders_batch) >= batch_size or len(awards_batch) >= batch_size:
                flush_batches()

    flush_batches()
    return tenders_count, awards_count


def rebuild_cache(
    years: list[int | str],
    db_path: str | Path,
    data_dir: str | Path,
    skip_download: bool = False,
) -> None:
    """Download and ingest all specified years into the SQLite cache."""
    db_path = Path(db_path)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = init_db(db_path)
    total_tenders = 0
    total_awards = 0

    for year in sorted(years, key=lambda y: int(y)):
        try:
            if not skip_download:
                file_path = download_year(year, data_dir)
            else:
                file_path = data_dir / f"{year}.jsonl.gz"
                if not file_path.exists():
                    logger.warning(f"File {file_path} not found; skipping year {year}")
                    continue

            logger.info(f"Ingesting {file_path.name}...")
            t_count, a_count = ingest_file(file_path, conn)
            total_tenders += t_count
            total_awards += a_count
            logger.info(f"Year {year} complete: +{t_count:,} tenders, +{a_count:,} awards")
        except Exception as e:
            logger.error(f"Error processing year {year}: {e}", exc_info=True)

    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM tenders")
    db_tenders = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM awards")
    db_awards = cursor.fetchone()[0]
    conn.close()

    logger.info(f"Database build complete at {db_path}!")
    logger.info(f"Total tenders in SQLite: {db_tenders:,}")
    logger.info(f"Total awards in SQLite: {db_awards:,}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Kenya OCDS releases into SQLite cache")
    parser.add_argument(
        "--years",
        nargs="+",
        default=["2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"],
        help="Years of OCDS data to ingest",
    )
    parser.add_argument("--db", default="data/thamani.sqlite", help="Path to SQLite database file")
    parser.add_argument("--data-dir", default="data", help="Directory for downloaded jsonl.gz files")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading archives")
    args = parser.parse_args()

    rebuild_cache(
        years=args.years,
        db_path=args.db,
        data_dir=args.data_dir,
        skip_download=args.skip_download,
    )


if __name__ == "__main__":
    main()
