#!/usr/bin/env python3
"""Scrape HN and upload to Supabase."""
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add pipeline directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from supabase import create_client

from collectors import HackerNewsCollector

# Load .env from pipeline directory
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def scrape_and_upload(hours_back: int = 24):
    """Scrape HN posts and upload to Supabase."""
    since = datetime.utcnow() - timedelta(hours=hours_back)

    logger.info(f"Scraping HN posts since {since}")

    # Collect from HN
    collector = HackerNewsCollector(
        top_stories_limit=500,
        new_stories_limit=200
    )

    try:
        posts = collector.fetch(since)
        logger.info(f"Collected {len(posts)} posts from HN")

        if not posts:
            logger.warning("No posts collected")
            return 0

        # Convert to Supabase format
        rows = []
        for post in posts:
            rows.append({
                "id": post.id,
                "source": post.source,
                "collected_at": datetime.utcnow().isoformat(),
                "created_at": post.created_at.isoformat() if post.created_at else None,
                "text": post.text,
                "url": post.url,
                "score": post.score,
                "metadata": post.metadata
            })

        # Upsert to Supabase (avoids duplicates)
        logger.info(f"Uploading {len(rows)} posts to Supabase...")

        # Batch insert in chunks of 100
        chunk_size = 100
        total_inserted = 0

        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            result = supabase.table("raw_posts").upsert(chunk, on_conflict="id").execute()
            total_inserted += len(chunk)
            logger.info(f"Uploaded {total_inserted}/{len(rows)} posts")

        logger.info(f"Done! Uploaded {total_inserted} posts to Supabase")
        return total_inserted

    finally:
        collector.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scrape HN to Supabase")
    parser.add_argument("--hours", type=int, default=168, help="Hours to look back (default: 168 = 7 days)")
    args = parser.parse_args()

    scrape_and_upload(args.hours)
