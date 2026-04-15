"""
Crunchbase Scraper
Pulls: funding rounds, investor tier, valuation step-ups, total raised
Writes output to data/raw/{company_name}/crunchbase.json

Required env vars:
  CRUNCHBASE_API_KEY  (from Crunchbase Basic or Pro plan)
"""

import os
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path


API_KEY = os.getenv("CRUNCHBASE_API_KEY")
BASE_URL = "https://api.crunchbase.com/api/v4"

TIER1_INVESTORS = {
    "sequoia capital", "andreessen horowitz", "a16z", "benchmark", "founders fund",
    "accel", "lightspeed venture partners", "kleiner perkins", "greylock", "index ventures",
    "general catalyst", "khosla ventures", "coatue", "tiger global", "dst global",
    "insight partners", "softbank", "ycombinator", "y combinator",
}


def get_org(permalink: str) -> dict:
    url = f"{BASE_URL}/entities/organizations/{permalink}"
    params = {
        "user_key": API_KEY,
        "field_ids": "short_description,total_funding_usd,num_funding_rounds,last_funding_type,last_funding_at,ipo_status,founded_on",
        "card_ids": "raised_funding_rounds,investors",
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    return r.json()


def classify_investor_tier(investor_name: str) -> str:
    if investor_name.lower() in TIER1_INVESTORS:
        return "tier1"
    return "other"


def scrape(company_name: str, crunchbase_permalink: str) -> dict:
    if not API_KEY:
        return {
            "company_name": company_name,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "error": "CRUNCHBASE_API_KEY not set",
        }

    print(f"  Fetching Crunchbase data for {company_name} ({crunchbase_permalink})...")
    data = get_org(crunchbase_permalink)
    props = data.get("properties", {})
    cards = data.get("cards", {})

    rounds = cards.get("raised_funding_rounds", [])
    investors = cards.get("investors", [])

    round_list = []
    for rd in rounds:
        rd_props = rd.get("properties", {})
        round_list.append({
            "announced_on": rd_props.get("announced_on"),
            "series": rd_props.get("funding_type"),
            "money_raised_usd": rd_props.get("money_raised", {}).get("value_usd") if isinstance(rd_props.get("money_raised"), dict) else rd_props.get("money_raised_usd"),
            "investor_count": rd_props.get("num_investors"),
        })

    investor_list = []
    tier1_count = 0
    for inv in investors:
        inv_props = inv.get("properties", {})
        name = inv_props.get("investor_identifier", {}).get("value", "")
        tier = classify_investor_tier(name)
        if tier == "tier1":
            tier1_count += 1
        investor_list.append({"name": name, "tier": tier})

    # Compute valuation step-ups across rounds if money_raised is available
    sorted_rounds = sorted(round_list, key=lambda x: x.get("announced_on") or "")
    step_ups = []
    for i in range(1, len(sorted_rounds)):
        prev = sorted_rounds[i - 1].get("money_raised_usd") or 0
        curr = sorted_rounds[i].get("money_raised_usd") or 0
        if prev > 0:
            step_ups.append(round(curr / prev, 2))

    result = {
        "company_name": company_name,
        "crunchbase_permalink": crunchbase_permalink,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_funding_usd": props.get("total_funding_usd"),
        "num_funding_rounds": props.get("num_funding_rounds"),
        "last_funding_type": props.get("last_funding_type"),
        "last_funding_at": props.get("last_funding_at"),
        "ipo_status": props.get("ipo_status"),
        "founded_on": props.get("founded_on"),
        "funding_rounds": round_list,
        "investors": investor_list,
        "tier1_investor_count": tier1_count,
        "round_size_step_ups": step_ups,
    }
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "crunchbase.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Crunchbase signals for a company")
    parser.add_argument("company", help="Company name")
    parser.add_argument("permalink", help="Crunchbase permalink (e.g. 'cursor' or 'supabase')")
    args = parser.parse_args()

    data = scrape(args.company, args.permalink)
    out_file = write_output(args.company, data)
    print(f"  Output written to: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
