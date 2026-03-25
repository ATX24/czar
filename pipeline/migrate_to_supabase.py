"""Migrate DuckDB data to Supabase.

Usage:
    1. Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env
    2. Run the SQL schema in supabase_schema.sql via the Supabase SQL Editor
    3. Run: python3 migrate_to_supabase.py
"""
import json
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
DB_PATH = Path(__file__).parent / "data" / "trends.duckdb"

BATCH_SIZE = 500


def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")
        sys.exit(1)

    # Import here so missing dep gives clear error
    try:
        from supabase import create_client
    except ImportError:
        print("Installing supabase-py...")
        os.system(f"{sys.executable} -m pip install supabase")
        from supabase import create_client

    if not DB_PATH.exists():
        print(f"ERROR: DuckDB not found at {DB_PATH}")
        sys.exit(1)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Count posts
    total = conn.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
    print(f"Found {total} posts in DuckDB")

    if total == 0:
        print("Nothing to migrate.")
        return

    # Fetch all posts
    rows = conn.execute(
        "SELECT id, source, collected_at, created_at, text, url, score, metadata "
        "FROM raw_posts ORDER BY created_at"
    ).fetchall()

    columns = ["id", "source", "collected_at", "created_at", "text", "url", "score", "metadata"]

    migrated = 0
    skipped = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        records = []
        for row in batch:
            record = {}
            for col, val in zip(columns, row):
                if col in ("collected_at", "created_at") and val is not None:
                    record[col] = val.isoformat() if hasattr(val, "isoformat") else str(val)
                elif col == "metadata":
                    if isinstance(val, str):
                        record[col] = json.loads(val)
                    elif isinstance(val, dict):
                        record[col] = val
                    else:
                        record[col] = {}
                else:
                    record[col] = val
            records.append(record)

        try:
            sb.table("raw_posts").upsert(records).execute()
            migrated += len(records)
            print(f"  Migrated {migrated}/{total} posts...")
        except Exception as e:
            print(f"  Error on batch {i//BATCH_SIZE}: {e}")
            skipped += len(records)

    conn.close()
    print(f"\nDone! Migrated: {migrated}, Skipped/Errored: {skipped}")


if __name__ == "__main__":
    main()
