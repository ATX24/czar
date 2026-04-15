"""
HN Scraper (Hacker News via Algolia API)
Pulls: founder history, company mentions, Show HN posts, Ask HN mentions
Writes output to data/raw/{company_name}/hn.json
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path


ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


def search_mentions(query: str, tags: str = "story", num_pages: int = 3) -> list:
    results = []
    for page in range(num_pages):
        url = f"{ALGOLIA_BASE}/search?query={query}&tags={tags}&hitsPerPage=50&page={page}"
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("hits", []))
    return results


def scrape(company_name: str, founder_names: list = None) -> dict:
    print(f"  Fetching HN mentions for {company_name}...")
    company_hits = search_mentions(company_name)

    founder_hits = []
    if founder_names:
        for founder in founder_names:
            print(f"  Fetching HN mentions for founder: {founder}...")
            hits = search_mentions(founder)
            founder_hits.extend(hits)

    result = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "company_mention_count": len(company_hits),
        "founder_mention_count": len(founder_hits),
        "top_company_posts": [
            {
                "title": h.get("title"),
                "url": h.get("url"),
                "points": h.get("points"),
                "num_comments": h.get("num_comments"),
                "created_at": h.get("created_at"),
                "author": h.get("author"),
            }
            for h in sorted(company_hits, key=lambda x: x.get("points") or 0, reverse=True)[:10]
        ],
    }
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "hn.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape HN signals for a company")
    parser.add_argument("company", help="Company name")
    parser.add_argument("--founders", nargs="*", help="Founder names to search")
    args = parser.parse_args()

    data = scrape(args.company, args.founders)
    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
