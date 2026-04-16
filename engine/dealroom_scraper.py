"""
Dealroom Scraper

Scrapes app.dealroom.co/companies/{slug} for funding signals.
Dealroom pages are JS-rendered but embed their data in a Nuxt __NUXT_DATA__ blob.

Extracts: total funding, round history, investor names, founding year, valuation.

Usage:
  python engine/dealroom_scraper.py "Anthropic"
  python engine/dealroom_scraper.py "Cursor" --slug anysphere

API key (optional): DEALROOM_API_KEY from https://developer.dealroom.co
  Free tier requires a business email to register.
"""

import os
import re
import json
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

try:
    import cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _HAS_CLOUDSCRAPER = False

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

API_KEY  = os.getenv("DEALROOM_API_KEY")
BASE_URL = "https://api.dealroom.co/api/v1"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://app.dealroom.co/",
}

TIER1_INVESTORS = {
    "sequoia capital", "andreessen horowitz", "a16z", "benchmark", "founders fund",
    "accel", "lightspeed venture partners", "kleiner perkins", "greylock", "index ventures",
    "general catalyst", "khosla ventures", "coatue", "tiger global", "dst global",
    "insight partners", "softbank", "ycombinator", "y combinator", "first round capital",
    "spark capital", "bessemer venture partners", "redpoint ventures", "union square ventures",
}


def name_to_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug.strip("-")


def _make_session():
    if _HAS_CLOUDSCRAPER:
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin"})
    else:
        s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _extract_nuxt_data(html: str) -> list:
    """Extract Nuxt __NUXT_DATA__ payload (array of primitives + objects)."""
    match = re.search(r'<script[^>]+id=["\']__NUXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Also try window.__NUXT__
    match = re.search(r'window\.__NUXT__\s*=\s*(\{.*?\})\s*;', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return []


def _extract_inline_json(html: str) -> dict:
    """Find any large JSON blob in script tags that looks like company data."""
    candidates = re.findall(r'<script[^>]*>\s*(\{.*?\})\s*</script>', html, re.DOTALL)
    for raw in candidates:
        if len(raw) < 200:
            continue
        try:
            obj = json.loads(raw)
            if any(k in str(obj) for k in ("total_raised", "funding_rounds", "investors")):
                return obj
        except json.JSONDecodeError:
            pass
    return {}


def _deep_find(obj, *keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
        for v in obj.values():
            r = _deep_find(v, *keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _deep_find(item, *keys)
            if r is not None:
                return r
    return None


def _parse_dealroom_blob(blob) -> dict:
    """Parse whatever JSON structure we found from the page."""
    result = {
        "total_funding_usd": None,
        "last_valuation_usd": None,
        "num_funding_rounds": None,
        "last_funding_type": None,
        "last_funding_at": None,
        "founded_on": None,
        "funding_rounds": [],
        "investors": [],
        "tier1_investor_count": 0,
    }
    if not blob:
        return result

    # Flatten list into searchable dict if needed
    if isinstance(blob, list):
        blob_dict = {}
        for item in blob:
            if isinstance(item, dict):
                blob_dict.update(item)
        blob = blob_dict

    def _usd_val(v):
        if isinstance(v, dict):
            return v.get("value_usd") or v.get("usd") or v.get("value") or v.get("amount")
        if isinstance(v, (int, float)):
            return v
        return None

    result["total_funding_usd"] = _usd_val(
        _deep_find(blob, "total_raised", "total_funding", "total_funding_usd", "raised_total")
    )
    result["last_valuation_usd"] = _usd_val(
        _deep_find(blob, "last_valuation", "valuation", "latest_valuation")
    )
    result["num_funding_rounds"] = _deep_find(blob, "num_funding_rounds", "rounds_count", "funding_rounds_count")

    last_at = _deep_find(blob, "last_funding_at", "last_round_date", "latest_funding_date")
    result["last_funding_at"] = last_at.get("value") if isinstance(last_at, dict) else last_at

    founded = _deep_find(blob, "founded_on", "founded", "founding_date", "launch_year")
    result["founded_on"] = founded.get("value") if isinstance(founded, dict) else founded

    # Rounds
    rounds_raw = _deep_find(blob, "funding_rounds", "rounds", "investments")
    if isinstance(rounds_raw, list):
        for rd in rounds_raw:
            if not isinstance(rd, dict):
                continue
            result["funding_rounds"].append({
                "announced_on": rd.get("date") or rd.get("announced_on"),
                "series": rd.get("round_type") or rd.get("type") or rd.get("series"),
                "money_raised_usd": _usd_val(rd.get("raised") or rd.get("amount")),
                "investor_count": rd.get("num_investors") or rd.get("investors_count"),
            })

    # Investors
    investors_raw = _deep_find(blob, "investors", "lead_investors", "backers")
    if isinstance(investors_raw, list):
        for inv in investors_raw:
            if isinstance(inv, str):
                name = inv
            elif isinstance(inv, dict):
                name = inv.get("name") or inv.get("title") or inv.get("investor_name") or ""
            else:
                continue
            if not name:
                continue
            tier = "tier1" if name.lower() in TIER1_INVESTORS else "other"
            if tier == "tier1":
                result["tier1_investor_count"] += 1
            result["investors"].append({"name": name, "tier": tier})

    return result


# ---------------------------------------------------------------------------
# HTML scraper
# ---------------------------------------------------------------------------

def scrape_html(company_name: str, slug: str = None) -> dict:
    slug = slug or name_to_slug(company_name)
    url  = f"https://app.dealroom.co/companies/{slug}"
    print(f"  [dealroom-html] Fetching {url}")

    session = _make_session()
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        return {
            "company_name": company_name,
            "slug": slug,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": "dealroom_html",
            "error": str(e),
        }

    nuxt_data = _extract_nuxt_data(resp.text)
    inline    = _extract_inline_json(resp.text)
    blob      = nuxt_data or inline

    parsed = _parse_dealroom_blob(blob)
    parsed["company_name"] = company_name
    parsed["slug"]         = slug
    parsed["scraped_at"]   = datetime.now(timezone.utc).isoformat()
    parsed["source"]       = "dealroom_html"

    print(f"  [dealroom-html] total=${parsed.get('total_funding_usd')} "
          f"| valuation=${parsed.get('last_valuation_usd')} "
          f"| founded={parsed.get('founded_on')}")
    return parsed


# ---------------------------------------------------------------------------
# API scraper (optional, requires DEALROOM_API_KEY)
# ---------------------------------------------------------------------------

def scrape_api(company_name: str, slug: str = None) -> dict:
    if not API_KEY:
        raise RuntimeError("DEALROOM_API_KEY not set — get one at https://developer.dealroom.co")

    headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
    slug = slug or name_to_slug(company_name)

    # Search by name to get Dealroom ID
    search_url = f"{BASE_URL}/companies"
    resp = requests.get(search_url, headers=headers,
                        params={"q": company_name, "per_page": 3}, timeout=15)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise ValueError(f"No Dealroom results for: {company_name}")

    company_id = items[0].get("id")
    matched    = items[0].get("name", company_name)
    print(f"  [dealroom-api] Matched: {matched} (id={company_id})")

    detail_url = f"{BASE_URL}/companies/{company_id}"
    resp = requests.get(detail_url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    rounds_raw   = data.get("funding_rounds", [])
    investors_raw = data.get("investors", [])

    round_list, investor_list, tier1_count = [], [], 0
    for rd in rounds_raw:
        round_list.append({
            "announced_on": rd.get("date"),
            "series": rd.get("round_type"),
            "money_raised_usd": rd.get("raised_usd") or rd.get("amount_usd"),
            "investor_count": rd.get("num_investors"),
        })
    for inv in investors_raw:
        name = inv.get("name", "")
        tier = "tier1" if name.lower() in TIER1_INVESTORS else "other"
        if tier == "tier1":
            tier1_count += 1
        investor_list.append({"name": name, "tier": tier})

    return {
        "company_name": company_name,
        "slug": slug,
        "dealroom_id": company_id,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "dealroom_api",
        "total_funding_usd": data.get("total_raised_usd") or data.get("total_funding"),
        "last_valuation_usd": data.get("latest_valuation") or data.get("last_valuation"),
        "num_funding_rounds": data.get("funding_rounds_count") or len(rounds_raw),
        "last_funding_type": data.get("last_round_type"),
        "last_funding_at": data.get("last_round_date"),
        "founded_on": data.get("founded") or data.get("launch_date"),
        "funding_rounds": round_list,
        "investors": investor_list,
        "tier1_investor_count": tier1_count,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape(company_name: str, slug: str = None) -> dict:
    """Try HTML first; fall back to API if key set and HTML yields no data."""
    result = scrape_html(company_name, slug)
    has_data = (
        result.get("total_funding_usd") is not None or
        result.get("funding_rounds") or
        result.get("last_valuation_usd") is not None
    )
    if not has_data and API_KEY:
        print(f"  [dealroom] HTML yielded no data — trying API...")
        try:
            result = scrape_api(company_name, slug)
        except Exception as e:
            result["api_fallback_error"] = str(e)
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir   = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file  = out_dir / "dealroom.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Dealroom for a company")
    parser.add_argument("company", help="Company name (e.g. 'Anthropic')")
    parser.add_argument("--slug", default=None,
                        help="Dealroom slug override")
    args = parser.parse_args()

    data     = scrape(args.company, args.slug)
    out_file = write_output(args.company, data)
    print(f"\nOutput: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
