"""
Crunchbase Scraper

Primary:  HTML scraping of crunchbase.com/organization/{slug} — no key needed.
Fallback: Crunchbase Basic API (200 req/day free) if CRUNCHBASE_API_KEY is set.

Extracts: total funding, round history, investor names, founding year, step-up multiples.

Usage:
  python engine/crunchbase_scraper.py "Anthropic"
  python engine/crunchbase_scraper.py "Anthropic" --slug anthropic
"""

import os
import re
import json
import time
import math
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
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

API_KEY  = os.getenv("CRUNCHBASE_API_KEY")
BASE_URL = "https://api.crunchbase.com/api/v4"

TIER1_INVESTORS = {
    "sequoia capital", "andreessen horowitz", "a16z", "benchmark", "founders fund",
    "accel", "lightspeed venture partners", "kleiner perkins", "greylock", "index ventures",
    "general catalyst", "khosla ventures", "coatue", "tiger global", "dst global",
    "insight partners", "softbank", "ycombinator", "y combinator", "first round capital",
    "spark capital", "bessemer venture partners", "redpoint ventures", "union square ventures",
    "battery ventures", "iVP", "institutional venture partners", "felicis",
}


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def name_to_slug(name: str) -> str:
    """Best-effort: 'Physical Intelligence' -> 'physical-intelligence'"""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = slug.strip("-")
    return slug


def classify_investor_tier(investor_name: str) -> str:
    return "tier1" if investor_name.lower() in TIER1_INVESTORS else "other"


# ---------------------------------------------------------------------------
# HTML scraper (primary — no API key needed)
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.crunchbase.com/",
}


def _make_session():
    if _HAS_CLOUDSCRAPER:
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin"})
        s.headers.update(_HEADERS)
        return s
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _deep_find(obj, *keys):
    """Recursively search nested dict/list for the first matching key path."""
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                return obj[key]
        for v in obj.values():
            result = _deep_find(v, *keys)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find(item, *keys)
            if result is not None:
                return result
    return None


def _extract_next_data(html: str) -> dict:
    """Pull the __NEXT_DATA__ JSON blob embedded in Crunchbase HTML."""
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: any script tag with a large JSON object
    for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        script = script.strip()
        if script.startswith("{") and "total_funding" in script:
            try:
                return json.loads(script)
            except json.JSONDecodeError:
                pass
    return {}


def _parse_funding_from_next_data(data: dict, slug: str) -> dict:
    """
    Walk the __NEXT_DATA__ blob and extract funding fields.
    Crunchbase's page data format changes; we use flexible key searching.
    """
    result = {
        "total_funding_usd": None,
        "num_funding_rounds": None,
        "last_funding_type": None,
        "last_funding_at": None,
        "founded_on": None,
        "funding_rounds": [],
        "investors": [],
        "tier1_investor_count": 0,
        "round_size_step_ups": [],
    }

    # Try to find the entity data blob (varies by page version)
    entity = None
    # Path 1: props.pageProps.entity (older pages)
    try:
        entity = data["props"]["pageProps"]["entity"]
    except (KeyError, TypeError):
        pass

    # Path 2: props.pageProps.detectedCountry sibling with organization data
    if entity is None:
        entity = _deep_find(data, "organization", "orgData", "entityData")

    # Path 3: search for keys directly
    if entity is None:
        entity = data

    props = {}
    if isinstance(entity, dict):
        props = entity.get("properties", entity)

    # --- scalar fields ---
    def _usd(v):
        if isinstance(v, dict):
            return v.get("value_usd") or v.get("value")
        return v

    result["total_funding_usd"] = _usd(
        props.get("funding_total") or
        props.get("total_funding_usd") or
        _deep_find(data, "funding_total", "total_funding_usd")
    )
    result["num_funding_rounds"] = (
        props.get("num_funding_rounds") or
        _deep_find(data, "num_funding_rounds")
    )
    result["last_funding_type"] = (
        props.get("last_funding_type") or
        _deep_find(data, "last_funding_type")
    )

    last_at = props.get("last_funding_at") or _deep_find(data, "last_funding_at")
    if isinstance(last_at, dict):
        last_at = last_at.get("value")
    result["last_funding_at"] = last_at

    founded = props.get("founded_on") or _deep_find(data, "founded_on")
    if isinstance(founded, dict):
        founded = founded.get("value")
    result["founded_on"] = founded

    # --- funding rounds ---
    rounds_raw = (
        _deep_find(data, "funding_rounds", "raised_funding_rounds") or
        props.get("funding_rounds", []) or []
    )
    if isinstance(rounds_raw, dict):
        rounds_raw = rounds_raw.get("nodes") or rounds_raw.get("edges") or []

    round_list = []
    for rd in (rounds_raw if isinstance(rounds_raw, list) else []):
        rp = rd.get("properties", rd) if isinstance(rd, dict) else {}
        round_list.append({
            "announced_on": rp.get("announced_on") or rp.get("date"),
            "series": rp.get("funding_type") or rp.get("series"),
            "money_raised_usd": _usd(rp.get("money_raised") or rp.get("money_raised_usd")),
            "investor_count": rp.get("num_investors"),
        })
    result["funding_rounds"] = round_list

    # --- investors ---
    investors_raw = (
        _deep_find(data, "investors", "lead_investors") or
        props.get("investors", []) or []
    )
    if isinstance(investors_raw, dict):
        investors_raw = investors_raw.get("nodes") or investors_raw.get("edges") or []

    investor_list = []
    tier1_count = 0
    for inv in (investors_raw if isinstance(investors_raw, list) else []):
        ip = inv.get("properties", inv) if isinstance(inv, dict) else {}
        raw_name = (
            ip.get("investor_identifier", {}).get("value") or
            ip.get("name") or ip.get("title") or
            (inv if isinstance(inv, str) else "")
        )
        if not raw_name:
            continue
        tier = classify_investor_tier(raw_name)
        if tier == "tier1":
            tier1_count += 1
        investor_list.append({"name": raw_name, "tier": tier})
    result["investors"] = investor_list
    result["tier1_investor_count"] = tier1_count

    # --- step-up multiples ---
    sorted_rounds = sorted(round_list, key=lambda x: x.get("announced_on") or "")
    step_ups = []
    for i in range(1, len(sorted_rounds)):
        prev = sorted_rounds[i - 1].get("money_raised_usd") or 0
        curr = sorted_rounds[i].get("money_raised_usd") or 0
        if prev and prev > 0 and curr:
            step_ups.append(round(curr / prev, 2))
    result["round_size_step_ups"] = step_ups

    return result


def scrape_html(company_name: str, slug: str = None) -> dict:
    """Scrape crunchbase.com/organization/{slug} directly (no API key)."""
    slug = slug or name_to_slug(company_name)
    url  = f"https://www.crunchbase.com/organization/{slug}"
    print(f"  [crunchbase-html] Fetching {url}")

    session = _make_session()
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        return {
            "company_name": company_name,
            "slug": slug,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": "crunchbase_html",
            "error": str(e),
        }

    next_data = _extract_next_data(resp.text)
    if not next_data:
        # Try BeautifulSoup fallback for visible text
        if _HAS_BS4:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Look for structured data (JSON-LD)
            for tag in soup.find_all("script", type="application/ld+json"):
                try:
                    next_data = json.loads(tag.string)
                    break
                except Exception:
                    pass

    parsed = _parse_funding_from_next_data(next_data, slug)
    parsed["company_name"] = company_name
    parsed["slug"]         = slug
    parsed["scraped_at"]   = datetime.now(timezone.utc).isoformat()
    parsed["source"]       = "crunchbase_html"

    total = parsed.get("total_funding_usd")
    rounds = len(parsed.get("funding_rounds", []))
    invs   = len(parsed.get("investors", []))
    print(f"  [crunchbase-html] total=${total} | {rounds} rounds | {invs} investors")

    return parsed


# ---------------------------------------------------------------------------
# API scraper (optional, requires CRUNCHBASE_API_KEY)
# ---------------------------------------------------------------------------

def _api_search_slug(name: str) -> str:
    url = f"{BASE_URL}/autocompletes"
    r = requests.get(url, params={
        "user_key": API_KEY, "query": name,
        "collection_ids": "organizations", "limit": 3,
    }, timeout=15)
    r.raise_for_status()
    entities = r.json().get("entities", [])
    if not entities:
        raise ValueError(f"No Crunchbase API results for: {name}")
    ident = entities[0].get("identifier", {})
    permalink = ident.get("permalink") or entities[0].get("permalink")
    print(f"  [crunchbase-api] Matched: {ident.get('value', name)} (slug={permalink})")
    return permalink


def scrape_api(company_name: str, slug: str = None) -> dict:
    if not API_KEY:
        raise RuntimeError("CRUNCHBASE_API_KEY not set")
    if slug is None:
        slug = _api_search_slug(company_name)

    url = f"{BASE_URL}/entities/organizations/{slug}"
    params = {
        "user_key": API_KEY,
        "field_ids": (
            "short_description,total_funding_usd,num_funding_rounds,"
            "last_funding_type,last_funding_at,ipo_status,founded_on"
        ),
        "card_ids": "raised_funding_rounds,investors",
    }
    print(f"  [crunchbase-api] Fetching {url}")
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data  = r.json()
    props = data.get("properties", {})
    cards = data.get("cards", {})

    rounds_raw = cards.get("raised_funding_rounds", [])
    invs_raw   = cards.get("investors", [])

    round_list = []
    for rd in rounds_raw:
        rp = rd.get("properties", {})
        mr = rp.get("money_raised", {})
        round_list.append({
            "announced_on": rp.get("announced_on"),
            "series": rp.get("funding_type"),
            "money_raised_usd": mr.get("value_usd") if isinstance(mr, dict) else rp.get("money_raised_usd"),
            "investor_count": rp.get("num_investors"),
        })

    investor_list, tier1_count = [], 0
    for inv in invs_raw:
        ip = inv.get("properties", {})
        name = ip.get("investor_identifier", {}).get("value", "")
        tier = classify_investor_tier(name)
        if tier == "tier1":
            tier1_count += 1
        investor_list.append({"name": name, "tier": tier})

    sorted_rounds = sorted(round_list, key=lambda x: x.get("announced_on") or "")
    step_ups = []
    for i in range(1, len(sorted_rounds)):
        prev = sorted_rounds[i-1].get("money_raised_usd") or 0
        curr = sorted_rounds[i].get("money_raised_usd") or 0
        if prev > 0 and curr:
            step_ups.append(round(curr / prev, 2))

    return {
        "company_name": company_name,
        "slug": slug,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "crunchbase_api",
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


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape(company_name: str, slug: str = None) -> dict:
    """Try HTML first; fall back to API if key is set and HTML yields no data."""
    result = scrape_html(company_name, slug)
    has_data = (
        result.get("total_funding_usd") is not None or
        result.get("funding_rounds") or
        result.get("investors")
    )
    if not has_data and API_KEY:
        print(f"  [crunchbase] HTML yielded no data — trying API...")
        try:
            result = scrape_api(company_name, slug)
        except Exception as e:
            result["api_fallback_error"] = str(e)
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir   = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file  = out_dir / "crunchbase.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Crunchbase for a company")
    parser.add_argument("company", help="Company name (e.g. 'Anthropic')")
    parser.add_argument("--slug", default=None,
                        help="Crunchbase slug override (e.g. 'anthropic')")
    args = parser.parse_args()

    data     = scrape(args.company, args.slug)
    out_file = write_output(args.company, data)
    print(f"\nOutput: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
