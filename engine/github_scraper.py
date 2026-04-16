"""
GitHub Scraper
Pulls: star count + 30-day trajectory, fork-to-star ratio, commit velocity (commits/week), contributor count
Writes output to data/raw/{company_name}/github.json
Validates against data/schema.json
"""

import os
import re
import json
import math
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env from repo root if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
BASE_URL = "https://api.github.com"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"
else:
    print("WARNING: GITHUB_TOKEN not set — rate limited to 60 req/hr")


# ---------------------------------------------------------------------------
# Core API calls
# ---------------------------------------------------------------------------

def get_repo(org: str, repo: str) -> dict:
    url = f"{BASE_URL}/repos/{org}/{repo}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def get_last_page(link_header: str) -> int:
    """Parse the last page number from a GitHub Link header."""
    match = re.search(r'page=(\d+)>; rel="last"', link_header or "")
    return int(match.group(1)) if match else 1


def get_star_trajectory_30d(org: str, repo: str, total_stars: int) -> dict:
    """
    Count stars gained in the last 30 days.

    GitHub's stargazers API returns stars chronologically (oldest first) but
    caps pagination at 400 pages (40,000 entries). For repos with >40k stars,
    the API won't expose the most recent entries, so we detect this and return
    a note instead of a misleading zero.
    """
    headers = {**HEADERS, "Accept": "application/vnd.github.star+json"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    API_PAGE_CAP = 400  # GitHub hard limit for this endpoint

    # Find total accessible pages
    url = f"{BASE_URL}/repos/{org}/{repo}/stargazers?per_page=100&page=1"
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    last_page = get_last_page(r.headers.get("Link", ""))

    api_capped = last_page >= API_PAGE_CAP
    accessible_stars = min(total_stars, last_page * 100)

    if last_page == 1:
        data = r.json()
        gained = sum(
            1 for e in data
            if datetime.fromisoformat(e["starred_at"].replace("Z", "+00:00")) >= cutoff
        )
        return {"stars_gained_30d": gained, "stars_30d_ago": total_stars - gained}

    # Fetch last accessible page to check how recent it is
    url_last = f"{BASE_URL}/repos/{org}/{repo}/stargazers?per_page=100&page={last_page}"
    r_last = requests.get(url_last, headers=headers)
    r_last.raise_for_status()
    last_entries = r_last.json()

    if not last_entries:
        return {"stars_gained_30d": None, "note": "No stargazer data returned"}

    most_recent_ts = datetime.fromisoformat(
        last_entries[-1]["starred_at"].replace("Z", "+00:00")
    )

    # If the API is capped and the newest accessible star is still old, we can't measure 30d
    if api_capped and most_recent_ts < cutoff:
        return {
            "stars_gained_30d": None,
            "stars_30d_ago": None,
            "note": (
                f"GitHub stargazer API capped at {API_PAGE_CAP * 100:,} entries. "
                f"Most recent accessible star: {most_recent_ts.date()}. "
                f"30d trajectory unavailable for repos with >{API_PAGE_CAP * 100:,} stars via this API."
            ),
        }

    # Walk backwards from last accessible page
    gained_30d = 0
    done = False

    for page in range(last_page, 0, -1):
        if page == last_page:
            entries = last_entries
        else:
            url = f"{BASE_URL}/repos/{org}/{repo}/stargazers?per_page=100&page={page}"
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            entries = r.json()

        for entry in reversed(entries):
            starred_at = datetime.fromisoformat(entry["starred_at"].replace("Z", "+00:00"))
            if starred_at >= cutoff:
                gained_30d += 1
            else:
                done = True
                break

        if done:
            break

    result = {"stars_gained_30d": gained_30d, "stars_30d_ago": total_stars - gained_30d}
    if api_capped:
        result["note"] = f"API capped at {API_PAGE_CAP * 100:,} accessible entries; count may be partial"
    return result


def get_commit_velocity(org: str, repo: str) -> dict:
    """
    Uses GitHub's commit_activity stats endpoint (last 52 weeks).
    Returns commits/week for the last 4 weeks and the last 52 weeks.
    Returns None values if GitHub hasn't computed stats yet (202 response).
    """
    url = f"{BASE_URL}/repos/{org}/{repo}/stats/commit_activity"
    r = requests.get(url, headers=HEADERS)

    if r.status_code == 202:
        return {
            "commits_last_4w": None,
            "commits_per_week_4w_avg": None,
            "commits_last_52w": None,
            "commits_per_week_52w_avg": None,
            "note": "GitHub computing stats — retry in ~30s",
        }

    r.raise_for_status()
    data = r.json()
    if not data:
        return {"commits_last_4w": None, "commits_per_week_4w_avg": None}

    last_4 = data[-4:]
    last_52 = data

    total_4w = sum(w["total"] for w in last_4)
    total_52w = sum(w["total"] for w in last_52)

    return {
        "commits_last_4w": total_4w,
        "commits_per_week_4w_avg": round(total_4w / 4, 2),
        "commits_last_52w": total_52w,
        "commits_per_week_52w_avg": round(total_52w / 52, 2),
    }


def get_contributor_count(org: str, repo: str) -> int:
    """
    Returns contributor count by reading the Link header's last page number.
    Each page holds 100 contributors, so last_page = ceil(total / 100).
    """
    url = f"{BASE_URL}/repos/{org}/{repo}/contributors?per_page=100&anon=false"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    last_page = get_last_page(r.headers.get("Link", ""))
    # Actual count: (last_page - 1) * 100 + len(last page)
    # For a quick approximation use last_page * 100 as ceiling
    # But to be precise: fetch the actual last page length
    if last_page == 1:
        return len(r.json())
    url_last = f"{BASE_URL}/repos/{org}/{repo}/contributors?per_page=100&page={last_page}&anon=false"
    r_last = requests.get(url_last, headers=HEADERS)
    r_last.raise_for_status()
    return (last_page - 1) * 100 + len(r_last.json())


def get_top_repo(org: str) -> dict:
    """Returns the most-starred repo for an org."""
    url = f"{BASE_URL}/orgs/{org}/repos?sort=stars&direction=desc&per_page=1"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    repos = r.json()
    if not repos:
        raise ValueError(f"No repos found for org: {org}")
    return repos[0]


# ---------------------------------------------------------------------------
# Main scrape entrypoint
# ---------------------------------------------------------------------------

def scrape(company_name: str, org: str, repo: str = None) -> dict:
    """
    Scrape GitHub signals for a company.
    If repo is None, tries org/org then falls back to the org's top repo.
    """
    repo_data = None

    if repo:
        repo_data = get_repo(org, repo)
    else:
        # Try common patterns first
        for candidate in [org, org.lower(), company_name.lower().replace(" ", "-")]:
            try:
                repo_data = get_repo(org, candidate)
                repo = candidate
                break
            except requests.HTTPError:
                continue

        if repo_data is None:
            print(f"  Auto-detecting top repo for {org}...")
            repo_data = get_top_repo(org)
            repo = repo_data["name"]
            print(f"  Selected: {org}/{repo}")

    stars = repo_data["stargazers_count"]
    forks = repo_data["forks_count"]

    print(f"  [{company_name}] {stars:,} stars — fetching 30d trajectory...")
    trajectory = get_star_trajectory_30d(org, repo, stars)

    print(f"  [{company_name}] fetching commit velocity...")
    commit_velocity = get_commit_velocity(org, repo)

    print(f"  [{company_name}] fetching contributor count...")
    contributor_count = get_contributor_count(org, repo)

    return {
        "company_name": company_name,
        "github_org": org,
        "github_repo": repo,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "stars": stars,
        "forks": forks,
        "fork_to_star_ratio": round(forks / stars, 4) if stars > 0 else None,
        "star_trajectory_30d": trajectory,
        "commit_velocity": commit_velocity,
        "contributor_count": contributor_count,
        "open_issues": repo_data.get("open_issues_count"),
        "watchers": repo_data.get("watchers_count"),
        "language": repo_data.get("language"),
        "description": repo_data.get("description"),
        "created_at": repo_data.get("created_at"),
        "pushed_at": repo_data.get("pushed_at"),
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def validate(data: dict) -> bool:
    schema_path = Path(__file__).parent.parent / "data" / "schema.json"
    if not schema_path.exists():
        return True
    with open(schema_path) as f:
        schema = json.load(f)
    required = schema.get("github", {}).get("required", [])
    missing = [f for f in required if f not in data]
    if missing:
        print(f"  Validation WARNING — missing fields: {missing}")
        return False
    print("  Schema validation: PASSED")
    return True


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(company_name: str, data: dict) -> Path:
    safe = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "github.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape GitHub signals for a company")
    parser.add_argument("company", help="Company name (e.g. 'Cursor')")
    parser.add_argument("org", help="GitHub org (e.g. 'getcursor')")
    parser.add_argument("--repo", default=None, help="Specific repo (auto-detects if omitted)")
    args = parser.parse_args()

    data = scrape(args.company, args.org, args.repo)
    validate(data)
    out_file = write_output(args.company, data)
    print(f"  Output: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
