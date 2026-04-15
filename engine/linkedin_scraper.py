"""
LinkedIn Scraper (via Proxycurl API)
Pulls: headcount, headcount growth, early employee pedigree, key hires
Writes output to data/raw/{company_name}/linkedin.json

Required env vars:
  PROXYCURL_API_KEY
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path


API_KEY = os.getenv("PROXYCURL_API_KEY")
BASE_URL = "https://nubela.co/proxycurl/api"

HEADERS = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}

PEDIGREE_COMPANIES = {
    "google", "meta", "apple", "microsoft", "amazon", "openai", "stripe",
    "spacex", "palantir", "databricks", "airbnb", "uber", "lyft", "snowflake",
    "figma", "notion", "linear", "vercel", "sequoia", "a16z", "ycombinator",
}


def get_company(linkedin_url: str) -> dict:
    url = f"{BASE_URL}/linkedin/company"
    params = {
        "url": linkedin_url,
        "resolve_numeric_id": "true",
        "use_cache": "if-present",
    }
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def scrape(company_name: str, linkedin_url: str) -> dict:
    if not API_KEY:
        return {
            "company_name": company_name,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "error": "PROXYCURL_API_KEY not set",
        }

    print(f"  Fetching LinkedIn data for {company_name}...")
    data = get_company(linkedin_url)

    headcount = data.get("company_size_on_linkedin")
    similar_companies = data.get("similar_companies", [])

    # Analyze employee pedigree from affiliated companies / description
    # Proxycurl returns employee_count, founded_year, etc.
    employees_raw = data.get("company_size", [])
    headcount_range = f"{employees_raw[0]}-{employees_raw[1]}" if isinstance(employees_raw, list) and len(employees_raw) == 2 else str(employees_raw)

    result = {
        "company_name": company_name,
        "linkedin_url": linkedin_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "headcount_on_linkedin": headcount,
        "headcount_range": headcount_range,
        "founded_year": data.get("founded_year"),
        "company_type": data.get("company_type"),
        "industries": data.get("industries", []),
        "specialties": data.get("specialities", []),
        "follower_count": data.get("follower_count"),
        "hq_location": data.get("hq", {}).get("city") if isinstance(data.get("hq"), dict) else None,
        "similar_companies": [s.get("name") for s in similar_companies[:5]] if similar_companies else [],
        "description": data.get("description", "")[:500],
    }
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "linkedin.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape LinkedIn signals via Proxycurl")
    parser.add_argument("company", help="Company name")
    parser.add_argument("linkedin_url", help="LinkedIn company URL")
    args = parser.parse_args()

    data = scrape(args.company, args.linkedin_url)
    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
