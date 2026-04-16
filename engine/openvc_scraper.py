"""
OpenVC Scraper

OpenVC (openvc.app) is a free, community-curated database of VC firms.
It surfaces which VCs are actively investing, in what stages/sectors,
and which portfolio companies they've backed.

This scraper uses two approaches:
  1. HTML: openvc.app/investors/{slug} — public, no auth needed
  2. Reverse: given a startup name, find VCs that list it in portfolio

Extracts per startup: which OpenVC-listed investors have backed it,
investor tier/stage focus, AUM proxies.

This complements Crunchbase/Dealroom investor lists with stage/focus metadata.

Usage:
  python engine/openvc_scraper.py "Anthropic"
  python engine/openvc_scraper.py "Cursor" --mode investors
"""

import re
import json
import argparse
import requests
from urllib.parse import urljoin, quote
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

BASE_URL = "https://openvc.app"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://openvc.app/",
}


def _make_session():
    if _HAS_CLOUDSCRAPER:
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin"})
    else:
        s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _extract_next_data(html: str) -> dict:
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
                      html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _parse_investor_page(data: dict, html: str) -> dict:
    """Parse a single VC firm page from __NEXT_DATA__."""
    result = {
        "name": None,
        "slug": None,
        "stage_focus": [],
        "sector_focus": [],
        "check_size_min_usd": None,
        "check_size_max_usd": None,
        "hq_location": None,
        "portfolio": [],
        "website": None,
    }
    if not data and not html:
        return result

    # Try to find investor props in __NEXT_DATA__
    props = {}
    try:
        props = data["props"]["pageProps"]
    except (KeyError, TypeError):
        pass

    inv = props.get("investor") or props.get("fund") or props.get("vc") or {}
    if not inv and isinstance(props, dict):
        # search for likely keys
        for v in props.values():
            if isinstance(v, dict) and ("stage" in v or "sector" in v or "portfolio" in v):
                inv = v
                break

    result["name"]            = inv.get("name") or inv.get("title")
    result["stage_focus"]     = inv.get("stages") or inv.get("stage_focus") or []
    result["sector_focus"]    = inv.get("sectors") or inv.get("sector_focus") or inv.get("verticals") or []
    result["hq_location"]     = inv.get("location") or inv.get("hq")
    result["website"]         = inv.get("website") or inv.get("url")

    checks = inv.get("check_size") or inv.get("investment_size") or {}
    if isinstance(checks, dict):
        result["check_size_min_usd"] = checks.get("min")
        result["check_size_max_usd"] = checks.get("max")
    elif isinstance(checks, str):
        # e.g. "$500K - $5M"
        nums = re.findall(r"[\d.,]+[KkMmBb]?", checks)
        def parse_num(s):
            s = s.replace(",", "")
            mult = 1
            if s[-1] in "Kk": mult = 1_000; s = s[:-1]
            elif s[-1] in "Mm": mult = 1_000_000; s = s[:-1]
            elif s[-1] in "Bb": mult = 1_000_000_000; s = s[:-1]
            try:
                return float(s) * mult
            except ValueError:
                return None
        if len(nums) >= 2:
            result["check_size_min_usd"] = parse_num(nums[0])
            result["check_size_max_usd"] = parse_num(nums[1])
        elif len(nums) == 1:
            result["check_size_min_usd"] = parse_num(nums[0])

    portfolio_raw = inv.get("portfolio") or inv.get("companies") or []
    if isinstance(portfolio_raw, list):
        result["portfolio"] = [
            (p.get("name") or p) if isinstance(p, dict) else p
            for p in portfolio_raw
        ]

    # BeautifulSoup fallback for visible text
    if _HAS_BS4 and html and not result["name"]:
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("h1")
        if title_tag:
            result["name"] = title_tag.get_text(strip=True)

        # Stage chips / tags
        for tag in soup.find_all(["span", "div"], class_=re.compile(r"stage|tag|badge|chip", re.I)):
            text = tag.get_text(strip=True)
            if text and len(text) < 40:
                result["stage_focus"].append(text)

    result["stage_focus"]  = list(dict.fromkeys(result["stage_focus"]))   # dedupe
    result["sector_focus"] = list(dict.fromkeys(result["sector_focus"]))
    return result


def search_investors_for_startup(company_name: str, session=None) -> list:
    """
    Search OpenVC for VCs that list this startup in their portfolio.
    Returns list of investor dicts.
    """
    if session is None:
        session = _make_session()

    # OpenVC search endpoint (may vary)
    search_urls = [
        f"{BASE_URL}/search?q={quote(company_name)}",
        f"{BASE_URL}/companies?q={quote(company_name)}",
    ]
    investors = []
    for url in search_urls:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            data = _extract_next_data(resp.text)
            # Look for results array
            results = None
            try:
                results = data["props"]["pageProps"].get("results") or \
                          data["props"]["pageProps"].get("investors") or \
                          data["props"]["pageProps"].get("companies")
            except (KeyError, TypeError):
                pass

            if results and isinstance(results, list):
                for item in results[:10]:
                    if isinstance(item, dict):
                        investors.append({
                            "name": item.get("name") or item.get("title", ""),
                            "slug": item.get("slug") or item.get("id"),
                            "type": item.get("type", "unknown"),
                        })
                break
        except Exception:
            continue

    return investors


def scrape(company_name: str, mode: str = "startup") -> dict:
    """
    mode='startup': find OpenVC-listed VCs that backed this company
    mode='investors': scrape all OpenVC investors (for building a reference list)
    """
    session = _make_session()
    print(f"  [openvc] Searching for '{company_name}'...")

    # Find matching investors who list this startup in portfolio
    backers = search_investors_for_startup(company_name, session)

    # Also try direct company page if it exists
    slug = company_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug).strip("-")

    company_page_data = {}
    for path in [f"/startups/{slug}", f"/companies/{slug}"]:
        try:
            resp = session.get(f"{BASE_URL}{path}", timeout=15)
            if resp.status_code == 200 and len(resp.text) > 5000:
                nd = _extract_next_data(resp.text)
                if nd:
                    company_page_data = nd
                    break
        except Exception:
            pass

    # Parse company page for investors listed there
    page_investors = []
    try:
        pp = company_page_data.get("props", {}).get("pageProps", {})
        co = pp.get("company") or pp.get("startup") or {}
        raw_invs = co.get("investors") or co.get("backers") or []
        for inv in raw_invs:
            if isinstance(inv, dict):
                page_investors.append({
                    "name": inv.get("name") or inv.get("title", ""),
                    "slug": inv.get("slug"),
                    "stage": inv.get("stage"),
                })
            elif isinstance(inv, str):
                page_investors.append({"name": inv})
    except Exception:
        pass

    # Merge backer lists
    all_investors = {i["name"]: i for i in (backers + page_investors) if i.get("name")}

    result = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "openvc_html",
        "openvc_investors": list(all_investors.values()),
        "openvc_investor_count": len(all_investors),
    }

    print(f"  [openvc] Found {len(all_investors)} investors for '{company_name}'")
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir   = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file  = out_dir / "openvc.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape OpenVC for a company's investors")
    parser.add_argument("company", help="Company name (e.g. 'Anthropic')")
    parser.add_argument("--mode", default="startup",
                        choices=["startup", "investors"],
                        help="startup: find backers; investors: list all VCs")
    args = parser.parse_args()

    data     = scrape(args.company, args.mode)
    out_file = write_output(args.company, data)
    print(f"\nOutput: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
