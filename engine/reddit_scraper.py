"""
Reddit Scraper
Pulls: subreddit mention counts, top posts, founder account history
Writes output to data/raw/{company_name}/reddit.json

Required env vars:
  REDDIT_CLIENT_ID
  REDDIT_CLIENT_SECRET
  REDDIT_USER_AGENT  (e.g. "czar-scraper/0.1 by youruser")
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path


CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
USER_AGENT = os.getenv("REDDIT_USER_AGENT", "czar-scraper/0.1")


def get_token() -> str:
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search_posts(query: str, token: str, limit: int = 25, subreddit: str = None) -> list:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    base = f"https://oauth.reddit.com/r/{subreddit}/search" if subreddit else "https://oauth.reddit.com/search"
    params = {"q": query, "sort": "top", "t": "year", "limit": limit, "type": "link"}
    if subreddit:
        params["restrict_sr"] = "on"
    r = requests.get(base, headers=headers, params=params)
    r.raise_for_status()
    return r.json()["data"]["children"]


def scrape(company_name: str, subreddits: list = None) -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        return {
            "company_name": company_name,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "error": "REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET not set",
        }

    token = get_token()

    print(f"  Searching Reddit for '{company_name}'...")
    global_posts = search_posts(company_name, token, limit=25)

    sub_results = {}
    for sub in (subreddits or []):
        print(f"  Searching r/{sub}...")
        try:
            posts = search_posts(company_name, token, limit=25, subreddit=sub)
            sub_results[sub] = len(posts)
        except requests.HTTPError as e:
            sub_results[sub] = f"error: {e}"

    top_posts = [
        {
            "title": p["data"]["title"],
            "subreddit": p["data"]["subreddit"],
            "score": p["data"]["score"],
            "num_comments": p["data"]["num_comments"],
            "url": p["data"]["url"],
            "created_utc": p["data"]["created_utc"],
        }
        for p in sorted(global_posts, key=lambda x: x["data"]["score"], reverse=True)[:10]
    ]

    result = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "global_mention_count": len(global_posts),
        "subreddit_mention_counts": sub_results,
        "top_posts": top_posts,
    }
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "reddit.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Reddit signals for a company")
    parser.add_argument("company", help="Company name")
    parser.add_argument("--subreddits", nargs="*", help="Subreddits to search within")
    args = parser.parse_args()

    data = scrape(args.company, args.subreddits)
    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
