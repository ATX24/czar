#!/usr/bin/env python3
"""Multi-source scraper: HN, Lobsters, Tech RSS feeds -> Supabase."""
import os
import sys
import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
import xml.etree.ElementTree as ET

# Add pipeline directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import httpx
from dotenv import load_dotenv
from supabase import create_client

# Load .env from czar root
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# RSS Feed sources (tech-focused)
RSS_FEEDS = {
    "techcrunch": "https://techcrunch.com/feed/",
    "verge": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "wired": "https://www.wired.com/feed/rss",
}


def parse_rss_date(date_str: str) -> Optional[datetime]:
    """Parse various RSS date formats."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def calculate_recency_score(created_at: datetime) -> int:
    """Calculate a score based on recency (newer = higher)."""
    now = datetime.utcnow()
    if created_at.tzinfo:
        created_at = created_at.replace(tzinfo=None)

    hours_old = (now - created_at).total_seconds() / 3600

    # Score decreases with age: 100 for <1h, down to 10 for >48h
    if hours_old < 1:
        return 100
    elif hours_old < 6:
        return 80
    elif hours_old < 12:
        return 60
    elif hours_old < 24:
        return 40
    elif hours_old < 48:
        return 20
    else:
        return 10


def fetch_rss_feed(url: str, source_name: str) -> List[Dict[str, Any]]:
    """Fetch and parse an RSS feed."""
    posts = []
    try:
        client = httpx.Client(timeout=30.0, follow_redirects=True)
        response = client.get(url)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        # Handle both RSS 2.0 and Atom feeds
        items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

        for item in items[:50]:  # Limit to 50 per source
            # RSS 2.0
            title = item.findtext('title') or item.findtext('{http://www.w3.org/2005/Atom}title') or ''
            link = item.findtext('link') or ''

            # Atom link handling
            if not link:
                link_elem = item.find('{http://www.w3.org/2005/Atom}link')
                if link_elem is not None:
                    link = link_elem.get('href', '')

            pub_date = item.findtext('pubDate') or item.findtext('{http://www.w3.org/2005/Atom}published') or item.findtext('{http://www.w3.org/2005/Atom}updated')
            description = item.findtext('description') or item.findtext('{http://www.w3.org/2005/Atom}summary') or ''
            author = item.findtext('author') or item.findtext('{http://purl.org/dc/elements/1.1/}creator') or item.findtext('{http://www.w3.org/2005/Atom}author/{http://www.w3.org/2005/Atom}name') or 'unknown'

            if not title or not link:
                continue

            # Generate unique ID
            post_id = f"{source_name}_{hashlib.md5(link.encode()).hexdigest()[:12]}"

            # Parse date
            created_at = parse_rss_date(pub_date) if pub_date else datetime.utcnow()

            # Calculate recency-based score
            recency_points = calculate_recency_score(created_at)

            posts.append({
                "id": post_id,
                "source": source_name,
                "collected_at": datetime.utcnow().isoformat(),
                "created_at": created_at.isoformat() if created_at else datetime.utcnow().isoformat(),
                "text": title,
                "url": link,
                "score": recency_points / 100,  # Normalize to 0-1
                "metadata": {
                    "author": author,
                    "points": recency_points,  # Use recency as "points"
                    "comments": 0,
                    "feed": source_name,
                    "score_type": "recency",
                }
            })

        client.close()
        logger.info(f"Fetched {len(posts)} posts from {source_name}")

    except Exception as e:
        logger.error(f"Failed to fetch {source_name}: {e}")

    return posts


def fetch_lobsters() -> List[Dict[str, Any]]:
    """Fetch from Lobsters JSON API."""
    posts = []
    try:
        client = httpx.Client(timeout=30.0)
        response = client.get("https://lobste.rs/hottest.json")
        response.raise_for_status()

        items = response.json()

        for item in items[:100]:
            post_id = f"lobsters_{item['short_id']}"
            points = item.get('score', 0)
            comments = item.get('comment_count', 0)

            posts.append({
                "id": post_id,
                "source": "lobsters",
                "collected_at": datetime.utcnow().isoformat(),
                "created_at": item.get('created_at', datetime.utcnow().isoformat()),
                "text": item.get('title', ''),
                "url": item.get('url') or item.get('comments_url'),
                "score": min(1.0, points / 100),
                "metadata": {
                    "author": item.get('submitter_user', 'unknown') if isinstance(item.get('submitter_user'), str) else item.get('submitter_user', {}).get('username', 'unknown'),
                    "points": points,
                    "comments": comments,
                    "tags": item.get('tags', []),
                }
            })

        client.close()
        logger.info(f"Fetched {len(posts)} posts from Lobsters")

    except Exception as e:
        logger.error(f"Failed to fetch Lobsters: {e}")

    return posts


def fetch_hn_best() -> List[Dict[str, Any]]:
    """Fetch top HN stories with 100+ points via RSS."""
    posts = []
    try:
        client = httpx.Client(timeout=30.0)
        response = client.get("https://hnrss.org/best?points=50&count=100")
        response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items:
            title = item.findtext('title') or ''
            link = item.findtext('link') or ''
            description = item.findtext('description') or ''
            pub_date = item.findtext('pubDate')
            creator = item.findtext('{http://purl.org/dc/elements/1.1/}creator') or 'unknown'
            comments_url = item.findtext('comments') or ''

            # Extract HN item ID from comments URL
            hn_id_match = re.search(r'item\?id=(\d+)', comments_url)
            hn_id = hn_id_match.group(1) if hn_id_match else hashlib.md5(link.encode()).hexdigest()[:12]

            # Extract points and comments from description
            points_match = re.search(r'Points:\s*(\d+)', description)
            comments_match = re.search(r'#\s*Comments:\s*(\d+)', description)

            points = int(points_match.group(1)) if points_match else 0
            comments = int(comments_match.group(1)) if comments_match else 0

            if not title or not link:
                continue

            post_id = f"hn_{hn_id}"
            created_at = parse_rss_date(pub_date) if pub_date else datetime.utcnow()

            posts.append({
                "id": post_id,
                "source": "hn",
                "collected_at": datetime.utcnow().isoformat(),
                "created_at": created_at.isoformat() if created_at else datetime.utcnow().isoformat(),
                "text": title,
                "url": link,
                "score": min(1.0, (points + comments * 2) / 1000),
                "metadata": {
                    "hn_id": int(hn_id) if hn_id.isdigit() else 0,
                    "by": creator,
                    "points": points,
                    "comments": comments,
                    "hn_url": comments_url,
                }
            })

        client.close()
        logger.info(f"Fetched {len(posts)} posts from HN Best")

    except Exception as e:
        logger.error(f"Failed to fetch HN Best: {e}")

    return posts


def upload_to_supabase(posts: List[Dict[str, Any]]) -> int:
    """Upload posts to Supabase."""
    if not posts:
        return 0

    chunk_size = 100
    total = 0

    for i in range(0, len(posts), chunk_size):
        chunk = posts[i:i + chunk_size]
        try:
            supabase.table("raw_posts").upsert(chunk, on_conflict="id").execute()
            total += len(chunk)
            logger.info(f"Uploaded {total}/{len(posts)} posts")
        except Exception as e:
            logger.error(f"Upload error: {e}")

    return total


def main():
    """Scrape all sources and upload to Supabase."""
    all_posts = []

    # Fetch from RSS feeds
    for source_name, feed_url in RSS_FEEDS.items():
        posts = fetch_rss_feed(feed_url, source_name)
        all_posts.extend(posts)

    # Fetch from Lobsters JSON API
    lobsters_posts = fetch_lobsters()
    all_posts.extend(lobsters_posts)

    # Fetch HN best stories
    hn_posts = fetch_hn_best()
    all_posts.extend(hn_posts)

    logger.info(f"Total posts collected: {len(all_posts)}")

    # Upload to Supabase
    if all_posts:
        uploaded = upload_to_supabase(all_posts)
        logger.info(f"Done! Uploaded {uploaded} posts to Supabase")
    else:
        logger.warning("No posts to upload")


if __name__ == "__main__":
    main()
