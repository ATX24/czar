"""
HN Scraper (Hacker News via Algolia API — no auth required)

Pulls per company:
  - Story mentions (title + comment body)
  - Show HN and Ask HN posts
  - Point-weighted engagement score
  - Top posts by score
  - Founder mention count + their top posts

Pulls per founder (optional):
  - Username submissions (if HN username known)
  - Name mentions in stories/comments

Writes output to data/raw/{company_name}/hn.json
"""

import json
import time
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


# ---------------------------------------------------------------------------
# Algolia API helpers
# ---------------------------------------------------------------------------

def algolia_search(query: str, tags: str, page: int = 0, hits_per_page: int = 50,
                   exact_phrase: bool = False) -> dict:
    """
    Single page search. tags examples: 'story', 'comment', 'show_hn', 'ask_hn'
    exact_phrase=True wraps query in quotes for Algolia phrase matching,
    reducing noise for generic company names (e.g. "Sierra", "Render", "Lambda").
    """
    url = f"{ALGOLIA_BASE}/search"
    q = f'"{query}"' if exact_phrase else query
    params = {
        "query": q,
        "tags": tags,
        "hitsPerPage": hits_per_page,
        "page": page,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def algolia_search_all(query: str, tags: str, max_pages: int = 5,
                       exact_phrase: bool = False) -> list:
    """Paginate through Algolia results, up to max_pages."""
    hits = []
    for page in range(max_pages):
        result = algolia_search(query, tags, page=page, exact_phrase=exact_phrase)
        page_hits = result.get("hits", [])
        hits.extend(page_hits)
        if page >= result.get("nbPages", 1) - 1:
            break
        time.sleep(0.1)
    return hits


def algolia_get_user(username: str) -> dict:
    """Fetch an HN user's profile."""
    url = f"{ALGOLIA_BASE}/users/{username}"
    r = requests.get(url, timeout=10)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


def algolia_user_submissions(username: str, max_pages: int = 3) -> list:
    """Fetch all stories submitted by an HN user."""
    url = f"{ALGOLIA_BASE}/search"
    params = {
        "tags": f"story,author_{username}",
        "hitsPerPage": 50,
    }
    hits = []
    for page in range(max_pages):
        params["page"] = page
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        hits.extend(data.get("hits", []))
        if page >= data.get("nbPages", 1) - 1:
            break
        time.sleep(0.1)
    return hits


# ---------------------------------------------------------------------------
# Summarizers
# ---------------------------------------------------------------------------

def summarize_post(hit: dict) -> dict:
    return {
        "title": hit.get("title") or hit.get("story_title"),
        "url": hit.get("url") or hit.get("story_url"),
        "points": hit.get("points") or 0,
        "num_comments": hit.get("num_comments") or 0,
        "author": hit.get("author"),
        "created_at": hit.get("created_at"),
        "objectID": hit.get("objectID"),
        "hn_link": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
    }


def engagement_score(posts: list) -> float:
    """Weighted score: points + 0.5 * comments."""
    return sum((p.get("points") or 0) + 0.5 * (p.get("num_comments") or 0) for p in posts)


# ---------------------------------------------------------------------------
# Main scrape
# ---------------------------------------------------------------------------

def scrape(
    company_name: str,
    founder_names: list = None,
    founder_hn_usernames: list = None,
    aliases: list = None,
    exact_phrase: bool = False,
) -> dict:
    """
    Args:
        company_name:          Primary search term (e.g. "Cursor")
        founder_names:         List of founder full names (e.g. ["Michael Truell"])
        founder_hn_usernames:  List of HN usernames for founders (e.g. ["truell"])
        aliases:               Additional search terms (e.g. ["Anysphere", "cursor.sh"])
    """
    search_terms = [company_name] + (aliases or [])
    all_story_hits = []
    all_comment_hits = []

    # --- Company story + comment mentions ---
    for term in search_terms:
        ep = exact_phrase or term in search_terms[1:]  # always exact for aliases
        print(f"  Searching HN stories for '{term}'" + (" [exact]" if ep else "") + "...")
        stories = algolia_search_all(term, tags="story", max_pages=5, exact_phrase=ep)
        all_story_hits.extend(stories)

        print(f"  Searching HN comments for '{term}'...")
        comments = algolia_search_all(term, tags="comment", max_pages=3, exact_phrase=ep)
        all_comment_hits.extend(comments)

    # Deduplicate by objectID
    seen = set()
    story_hits = []
    for h in all_story_hits:
        oid = h.get("objectID")
        if oid not in seen:
            seen.add(oid)
            story_hits.append(h)

    seen = set()
    comment_hits = []
    for h in all_comment_hits:
        oid = h.get("objectID")
        if oid not in seen:
            seen.add(oid)
            comment_hits.append(h)

    # --- Show HN + Ask HN ---
    print(f"  Searching Show HN for '{company_name}'...")
    show_hn_hits = algolia_search_all(company_name, tags="show_hn", max_pages=2, exact_phrase=exact_phrase)

    print(f"  Searching Ask HN for '{company_name}'...")
    ask_hn_hits = algolia_search_all(company_name, tags="ask_hn", max_pages=2, exact_phrase=exact_phrase)

    # --- Founder signals ---
    founder_story_hits = []
    founder_profiles = []

    for name in (founder_names or []):
        print(f"  Searching HN stories mentioning founder '{name}'...")
        hits = algolia_search_all(name, tags="story", max_pages=3)
        founder_story_hits.extend(hits)

    for username in (founder_hn_usernames or []):
        print(f"  Fetching HN profile for user '{username}'...")
        profile = algolia_get_user(username)
        submissions = algolia_user_submissions(username, max_pages=3)

        if profile:
            founder_profiles.append({
                "username": username,
                "karma": profile.get("karma"),
                "created_at": profile.get("created_at"),
                "about": (profile.get("about") or "")[:300],
                "submission_count": len(submissions),
                "top_submissions": sorted(
                    [summarize_post(s) for s in submissions],
                    key=lambda x: x["points"],
                    reverse=True,
                )[:5],
            })

    # --- Compute metrics ---
    top_stories = sorted(story_hits, key=lambda x: x.get("points") or 0, reverse=True)[:10]
    top_show_hn = sorted(show_hn_hits, key=lambda x: x.get("points") or 0, reverse=True)[:5]
    top_ask_hn = sorted(ask_hn_hits, key=lambda x: x.get("points") or 0, reverse=True)[:5]

    story_summaries = [summarize_post(h) for h in top_stories]
    total_eng = engagement_score([summarize_post(h) for h in story_hits])

    # Monthly mention distribution (last 12 months)
    now = datetime.now(timezone.utc)
    monthly_counts: dict = {}
    for h in story_hits:
        created = h.get("created_at")
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_months = (now.year - dt.year) * 12 + (now.month - dt.month)
                if 0 <= age_months < 12:
                    month_key = dt.strftime("%Y-%m")
                    monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
            except Exception:
                pass

    return {
        "company_name": company_name,
        "scraped_at": now.isoformat(),
        "search_terms_used": search_terms,
        "story_mention_count": len(story_hits),
        "comment_mention_count": len(comment_hits),
        "show_hn_count": len(show_hn_hits),
        "ask_hn_count": len(ask_hn_hits),
        "total_engagement_score": round(total_eng, 1),
        "monthly_story_counts_12m": dict(sorted(monthly_counts.items())),
        "top_stories": story_summaries,
        "top_show_hn": [summarize_post(h) for h in top_show_hn],
        "top_ask_hn": [summarize_post(h) for h in top_ask_hn],
        "founder_story_mention_count": len(founder_story_hits),
        "founder_profiles": founder_profiles,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(company_name: str, data: dict) -> Path:
    safe = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "hn.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape HN signals for a company (no API key needed)")
    parser.add_argument("company", help="Company name (e.g. 'Cursor')")
    parser.add_argument("--aliases", nargs="*", help="Additional search terms (e.g. Anysphere cursor.sh)")
    parser.add_argument("--founders", nargs="*", help="Founder full names (for mention search)")
    parser.add_argument("--hn-users", nargs="*", help="Founder HN usernames (for profile + submission data)")
    args = parser.parse_args()

    data = scrape(
        args.company,
        founder_names=args.founders,
        founder_hn_usernames=args.hn_users,
        aliases=args.aliases,
    )
    out_file = write_output(args.company, data)
    print(f"\n  Output: {out_file}")
    # Print summary instead of full dump (can be large)
    summary = {k: v for k, v in data.items() if k not in ("top_stories", "top_show_hn", "top_ask_hn", "founder_profiles")}
    summary["top_story"] = data["top_stories"][0] if data["top_stories"] else None
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
