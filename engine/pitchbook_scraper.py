"""
PitchBook Scraper
Pulls: funding rounds, round sizes, investors, valuation estimates, time between rounds

Requires a PitchBook Data API key — separate from standard PitchBook login.
To get access: contact your PitchBook account rep and request "Data API access."

Required env vars:
  PITCHBOOK_API_KEY   (issued by PitchBook, not your login credentials)

PitchBook Data API docs: https://data.pitchbook.com/docs
Base URL: https://api.pitchbook.com/api/v1  (confirm with your rep — may vary by tier)

Writes output to data/raw/{company_name}/pitchbook.json
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

API_KEY = os.getenv("PITCHBOOK_API_KEY")
BASE_URL = "https://api.pitchbook.com/api/v1"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
}

TIER1_INVESTORS = {
    "sequoia capital", "andreessen horowitz", "a16z", "benchmark", "founders fund",
    "accel", "lightspeed venture partners", "kleiner perkins", "greylock", "index ventures",
    "general catalyst", "khosla ventures", "coatue management", "tiger global management",
    "dst global", "insight partners", "softbank vision fund", "y combinator",
    "first round capital", "union square ventures", "spark capital", "matrix partners",
}


# ---------------------------------------------------------------------------
# API calls (endpoints subject to change — confirm with PitchBook rep)
# ---------------------------------------------------------------------------

def search_company(name: str) -> dict:
    """Search for a company by name and return the best match."""
    url = f"{BASE_URL}/companies/search"
    r = requests.get(url, headers=HEADERS, params={"query": name, "limit": 3}, timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise ValueError(f"No PitchBook results for: {name}")
    # Return the first (best) match
    return results[0]


def get_company(pb_id: str) -> dict:
    """Fetch full company profile by PitchBook ID."""
    url = f"{BASE_URL}/companies/{pb_id}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def get_funding_rounds(pb_id: str) -> list:
    """Fetch all funding rounds for a company."""
    url = f"{BASE_URL}/companies/{pb_id}/deals"
    r = requests.get(url, headers=HEADERS, params={"dealType": "Venture Capital"}, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def compute_round_velocity(rounds: list) -> dict:
    """Compute days between consecutive rounds."""
    dated = []
    for rd in rounds:
        date_str = rd.get("dealDate") or rd.get("closeDate")
        if date_str:
            try:
                dated.append(datetime.fromisoformat(date_str.replace("Z", "+00:00")))
            except Exception:
                pass
    dated.sort()

    gaps = []
    for i in range(1, len(dated)):
        gaps.append((dated[i] - dated[i - 1]).days)

    return {
        "num_rounds": len(dated),
        "avg_days_between_rounds": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "days_since_last_round": (datetime.now(timezone.utc) - dated[-1]).days if dated else None,
        "first_round_date": dated[0].date().isoformat() if dated else None,
        "last_round_date": dated[-1].date().isoformat() if dated else None,
    }


def classify_investors(rounds: list) -> dict:
    """Count tier-1 investors and list all unique investors."""
    all_investors = set()
    tier1 = set()
    for rd in rounds:
        for inv in rd.get("investors", []):
            name = (inv.get("name") or "").strip()
            if name:
                all_investors.add(name)
                if name.lower() in TIER1_INVESTORS:
                    tier1.add(name)
    return {
        "unique_investors": sorted(all_investors),
        "tier1_investors": sorted(tier1),
        "tier1_count": len(tier1),
    }


def compute_step_ups(rounds: list) -> list:
    """Compute round-over-round size step-up multiples."""
    sizes = []
    for rd in sorted(rounds, key=lambda x: x.get("dealDate") or ""):
        size = rd.get("dealSize") or rd.get("raisedAmount")
        if size:
            try:
                sizes.append(float(size))
            except Exception:
                pass

    step_ups = []
    for i in range(1, len(sizes)):
        if sizes[i - 1] > 0:
            step_ups.append(round(sizes[i] / sizes[i - 1], 2))
    return step_ups


# ---------------------------------------------------------------------------
# Main scrape
# ---------------------------------------------------------------------------

def scrape(company_name: str, pitchbook_id: str = None) -> dict:
    """
    Scrape PitchBook funding data for a company.
    If pitchbook_id is None, searches by company_name and uses the first result.
    """
    if not API_KEY:
        return {
            "company_name": company_name,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "error": "PITCHBOOK_API_KEY not set — request Data API access from your PitchBook rep",
        }

    if pitchbook_id is None:
        print(f"  Searching PitchBook for '{company_name}'...")
        match = search_company(company_name)
        pitchbook_id = match.get("id") or match.get("companyId")
        print(f"  Matched: {match.get('name')} (id={pitchbook_id})")

    print(f"  Fetching company profile...")
    company = get_company(pitchbook_id)

    print(f"  Fetching funding rounds...")
    rounds = get_funding_rounds(pitchbook_id)

    velocity = compute_round_velocity(rounds)
    investors = classify_investors(rounds)
    step_ups = compute_step_ups(rounds)

    total_raised = sum(
        float(rd.get("dealSize") or rd.get("raisedAmount") or 0)
        for rd in rounds
    )

    round_list = [
        {
            "date": rd.get("dealDate") or rd.get("closeDate"),
            "series": rd.get("dealType") or rd.get("seriesType"),
            "size_usd": rd.get("dealSize") or rd.get("raisedAmount"),
            "post_money_valuation": rd.get("postMoneyValuation"),
            "investors": [i.get("name") for i in rd.get("investors", [])],
        }
        for rd in sorted(rounds, key=lambda x: x.get("dealDate") or "")
    ]

    return {
        "company_name": company_name,
        "pitchbook_id": pitchbook_id,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_raised_usd": total_raised,
        "last_known_valuation": company.get("lastKnownValuation") or company.get("postMoneyValuation"),
        "hq_location": company.get("hqLocation"),
        "founded_year": company.get("foundedDate", "")[:4] or None,
        "employee_count": company.get("employeeCount"),
        "funding_rounds": round_list,
        "round_velocity": velocity,
        "investor_analysis": investors,
        "round_size_step_ups": step_ups,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(company_name: str, data: dict) -> Path:
    safe = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "pitchbook.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scrape PitchBook funding data")
    parser.add_argument("company", help="Company name")
    parser.add_argument("--id", dest="pb_id", default=None, help="PitchBook company ID (skips search)")
    args = parser.parse_args()

    data = scrape(args.company, args.pb_id)
    out_file = write_output(args.company, data)
    print(f"\n  Output: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
