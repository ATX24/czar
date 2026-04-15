"""
GitHub Scraper
Pulls: star count + 30-day trajectory, fork-to-star ratio, commit velocity (commits/week), contributor count
Writes output to data/raw/{company_name}/github.json
"""

import os
import json
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path


GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
BASE_URL = "https://api.github.com"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def get_repo(org: str, repo: str) -> dict:
    url = f"{BASE_URL}/repos/{org}/{repo}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def get_star_history_30d(org: str, repo: str) -> dict:
    """
    Approximates 30-day star trajectory by comparing stargazers from 30 days ago
    using the stargazers API with timestamps (requires Accept: application/vnd.github.star+json).
    Returns stars_30d_ago and net_gain.
    """
    headers = {**HEADERS, "Accept": "application/vnd.github.star+json"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    page = 1
    stars_before_cutoff = 0
    total_stars_seen = 0
    found_cutoff = False

    while True:
        url = f"{BASE_URL}/repos/{org}/{repo}/stargazers?per_page=100&page={page}"
        r = requests.get(url, headers=headers)
        if r.status_code == 404 or r.status_code == 422:
            break
        r.raise_for_status()
        data = r.json()
        if not data:
            break

        for entry in data:
            starred_at = datetime.fromisoformat(entry["starred_at"].replace("Z", "+00:00"))
            total_stars_seen += 1
            if starred_at < cutoff:
                stars_before_cutoff += 1
                found_cutoff = True

        # If all entries on this page are before cutoff, we can stop paginating
        # (stars are returned oldest-first)
        last_starred = datetime.fromisoformat(data[-1]["starred_at"].replace("Z", "+00:00"))
        if last_starred < cutoff:
            # All remaining pages are also before cutoff — skip the rest
            # We don't have a way to count them without fetching all pages,
            # so we note this is a partial count for large repos
            break

        page += 1

    return {
        "stars_30d_ago_approx": stars_before_cutoff,
        "stars_gained_30d_approx": total_stars_seen - stars_before_cutoff,
        "note": "Approximate: only fetches recent pages. For large repos, 30d delta may be underestimated.",
    }


def get_commit_velocity(org: str, repo: str) -> dict:
    """
    Uses the commit activity API (last 52 weeks) and returns commits/week for the last 4 weeks.
    """
    url = f"{BASE_URL}/repos/{org}/{repo}/stats/commit_activity"
    r = requests.get(url, headers=HEADERS)

    if r.status_code == 202:
        # GitHub is computing stats — return placeholder
        return {"commits_last_4w": None, "commits_per_week_avg": None, "note": "GitHub still computing stats, retry later"}

    r.raise_for_status()
    data = r.json()

    if not data:
        return {"commits_last_4w": None, "commits_per_week_avg": None}

    last_4_weeks = data[-4:]
    total = sum(week["total"] for week in last_4_weeks)
    avg = total / 4 if last_4_weeks else 0

    return {
        "commits_last_4w": total,
        "commits_per_week_avg": round(avg, 2),
    }


def get_contributor_count(org: str, repo: str) -> int:
    """
    Returns contributor count (capped at 500 due to GitHub API pagination limit).
    """
    url = f"{BASE_URL}/repos/{org}/{repo}/contributors?per_page=1&anon=false"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()

    # Use Link header to get total pages = total contributors
    link = r.headers.get("Link", "")
    if 'rel="last"' in link:
        # Extract last page number
        import re
        match = re.search(r'page=(\d+)>; rel="last"', link)
        if match:
            return int(match.group(1))

    data = r.json()
    return len(data)


def scrape(company_name: str, org: str, repo: str = None) -> dict:
    """
    Main scrape function. If repo is None, uses org name as repo (common pattern).
    Tries org/org first, then falls back to org's most-starred repo.
    """
    if repo is None:
        # Try a few common patterns
        candidates = [org, org.lower(), company_name.lower().replace(" ", "-")]
        repo_data = None
        for candidate in candidates:
            try:
                repo_data = get_repo(org, candidate)
                repo = candidate
                break
            except requests.HTTPError:
                continue

        if repo_data is None:
            # Fall back to org's most-starred repo
            url = f"{BASE_URL}/orgs/{org}/repos?sort=stars&direction=desc&per_page=1"
            r = requests.get(url, headers=HEADERS)
            r.raise_for_status()
            repos = r.json()
            if not repos:
                raise ValueError(f"No repos found for org {org}")
            repo_data = repos[0]
            repo = repo_data["name"]
            print(f"  Auto-selected top repo: {org}/{repo}")
    else:
        repo_data = get_repo(org, repo)

    stars = repo_data["stargazers_count"]
    forks = repo_data["forks_count"]

    print(f"  Fetching star history...")
    star_history = get_star_history_30d(org, repo)

    print(f"  Fetching commit velocity...")
    commit_velocity = get_commit_velocity(org, repo)

    print(f"  Fetching contributor count...")
    contributor_count = get_contributor_count(org, repo)

    result = {
        "company_name": company_name,
        "github_org": org,
        "github_repo": repo,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "stars": stars,
        "forks": forks,
        "fork_to_star_ratio": round(forks / stars, 4) if stars > 0 else None,
        "star_trajectory_30d": star_history,
        "commit_velocity": commit_velocity,
        "contributor_count": contributor_count,
        "open_issues": repo_data.get("open_issues_count"),
        "watchers": repo_data.get("watchers_count"),
        "language": repo_data.get("language"),
        "description": repo_data.get("description"),
        "created_at": repo_data.get("created_at"),
        "pushed_at": repo_data.get("pushed_at"),
    }

    return result


def load_schema() -> dict:
    schema_path = Path(__file__).parent.parent / "data" / "schema.json"
    if schema_path.exists():
        with open(schema_path) as f:
            return json.load(f)
    return {}


def validate(data: dict, schema: dict) -> bool:
    """Basic validation: check required fields exist and have correct types."""
    github_schema = schema.get("github", {})
    required_fields = github_schema.get("required", [])
    missing = [f for f in required_fields if f not in data]
    if missing:
        print(f"  Validation warning — missing fields: {missing}")
        return False
    return True


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "github.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape GitHub signals for a company")
    parser.add_argument("company", help="Company name (e.g. 'Cursor')")
    parser.add_argument("org", help="GitHub org (e.g. 'getcursor')")
    parser.add_argument("--repo", default=None, help="Specific repo name (optional, auto-detects if omitted)")
    args = parser.parse_args()

    print(f"Scraping GitHub for {args.company} ({args.org})...")
    data = scrape(args.company, args.org, args.repo)

    schema = load_schema()
    valid = validate(data, schema)
    if valid:
        print("  Schema validation: PASSED")
    else:
        print("  Schema validation: WARNING (see above)")

    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
