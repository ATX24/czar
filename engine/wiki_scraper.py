"""
Wikipedia Scraper

Pulls funding, investors, founders, and founding year from Wikipedia's
public Action API (no auth, no API key needed).

Works best for companies with a Wikipedia article that has a Funding section.
Falls back to extracting dollar amounts + investor names from the full article.

Extracts:
  - Total funding (sum of RAISED amounts only, not valuations)
  - Round history (series, amount, date, lead investors)
  - Founding year / founders
  - HQ location

Usage:
  python engine/wiki_scraper.py "Anthropic"
  python engine/wiki_scraper.py "Cursor" --title "Anysphere"
"""

import re
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

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_UA  = "czar-research-tool/1.0 (https://github.com/ATX24/czar)"

WIKI_TITLE_OVERRIDES = {
    "Cursor":                  "Anysphere",
    "Perplexity":              "Perplexity AI",
    "Physical Intelligence":   "Physical Intelligence (company)",
    "Together AI":             "Together AI",
    "Figure AI":               "Figure AI",
    "Shield AI":               "Shield AI",
    "Helion Energy":           "Helion Energy",
    "QuEra Computing":         "QuEra Computing",
    "Arc Boat Company":        "Arc (boat company)",
    "Relativity Space":        "Relativity Space",
    "Redwood Materials":       "Redwood Materials",
    "ElevenLabs":              "ElevenLabs",
    "Fireworks AI":            "Fireworks AI",
    "CoreWeave":               "CoreWeave",
    "Hippocratic AI":          "Hippocratic AI",
    "Skild AI":                "Skild AI",
    "Agility Robotics":        "Agility Robotics",
    "Gecko Robotics":          "Gecko Robotics",
    "7AI":                     "7AI (company)",
    "Fal":                     "Fal (platform)",
    "Val Town":                "Val Town",
}

TIER1_INVESTORS = {
    "sequoia capital", "andreessen horowitz", "a16z", "benchmark", "founders fund",
    "accel", "lightspeed venture partners", "kleiner perkins", "greylock", "index ventures",
    "general catalyst", "khosla ventures", "coatue", "tiger global", "dst global",
    "insight partners", "softbank", "ycombinator", "y combinator", "first round capital",
    "spark capital", "bessemer venture partners", "redpoint ventures", "union square ventures",
    "iconiq capital", "iconiq growth",
}

# Names that look like wikilinks but aren't investors
_NOT_INVESTOR = {
    # Media outlets
    "cnbc", "reuters", "bloomberg", "techcrunch", "forbes", "wired",
    "wall street journal", "new york times", "financial times", "the guardian",
    "venturebeat", "axios", "the verge", "ars technica", "mit technology review",
    # Generic finance/legal terms
    "stakeholder (corporate)", "post-money valuation", "pre-money valuation",
    "venture capital", "private equity", "initial public offering",
    "series a", "series b", "series c", "series d", "series e", "series f",
    "limited partnership", "general partner", "special purpose vehicle",
    # Tech concepts
    "cloud computing", "artificial intelligence", "machine learning",
    "large language model", "generative ai", "deep learning", "natural language processing",
    # Geography / government (unless direct investor, handle separately)
    "united states", "california", "new york", "san francisco", "silicon valley",
    # Social media / misc
    "youtube", "twitter", "linkedin", "facebook", "wikipedia",
    "xai (company)",  # ambiguous
    "amazon web services",  # keep "Amazon" as investor but not "Amazon Web Services" wikilink
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _usd(amount_str: str, unit: str) -> float:
    v = float(amount_str.replace(",", ""))
    u = unit.lower()
    if u in ("billion", "b"):
        return v * 1e9
    if u in ("million", "m"):
        return v * 1e6
    if u in ("k",):
        return v * 1e3
    return v


def _strip_refs(text: str) -> str:
    """Remove <ref>…</ref> blocks and inline templates."""
    text = re.sub(r'<ref[^>]*/>', '', text)
    text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)
    return text


def _strip_templates(text: str) -> str:
    """Remove {{...}} templates (up to 3 levels of nesting)."""
    for _ in range(3):
        text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    return text


def _extract_list_template(value: str) -> list[str]:
    """
    Pull items from {{Unbulleted list|item1|item2}} or {{Plain list|...}}.
    Returns list of cleaned strings, or [] if not a list template.
    """
    m = re.match(r'\{\{(?:Unbulleted list|Plain list|Flatlist|Hlist)\s*\|(.*)\}\}',
                 value.strip(), re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    # Split on '|' at depth=0 within the list template
    inner = m.group(1)
    # Use depth-aware split for wikilinks inside items
    items_raw, buf, d = [], [], 0
    for j, c in enumerate(inner):
        two = inner[j:j+2]
        if two in ('{{', '[['):
            d += 1; buf.append(c)
        elif two in ('}}', ']]'):
            d = max(0, d - 1); buf.append(c)
        elif c == '|' and d == 0:
            items_raw.append(''.join(buf)); buf = []
        else:
            buf.append(c)
    if buf:
        items_raw.append(''.join(buf))

    items = []
    for item in items_raw:
        # Strip refs BEFORE clean to remove dangling ref markup
        cleaned = _clean(_strip_refs(item))
        if cleaned and len(cleaned) > 1:
            items.append(cleaned)
    return items


def _extract_year_from_template(text: str) -> str | None:
    """Handle {{Start date and age|2021}} or {{Start date|2021|01|01}} → '2021'."""
    m = re.search(r'\{\{Start date[^|]*\|(\d{4})', text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'\{\{[Yy]ear\|(\d{4})\}\}', text)
    if m:
        return m.group(1)
    return None


def _clean(text: str) -> str:
    text = _strip_refs(text)
    text = _strip_templates(text)
    text = re.sub(r'\[\[(?:File|Image):[^\]]+\]\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[\[([^\]|]+\|)?([^\]]+)\]\]', r'\2', text)
    text = re.sub(r"'{2,3}", '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _extract_section(wikitext: str, heading: str) -> str:
    """Exact heading match (== Heading ==)."""
    m = re.search(
        rf'==+\s*{re.escape(heading)}\s*==+\s*(.*?)(?=\n==\s|\Z)',
        wikitext, re.DOTALL | re.IGNORECASE
    )
    return m.group(1).strip() if m else ""


def _extract_sections_containing(wikitext: str, keywords: list[str]) -> str:
    """
    Collect all sections whose heading contains any of the keywords.
    Also includes any sub-sections (===).
    """
    parts = []
    for kw in keywords:
        for m in re.finditer(
            rf'==+\s*[^=]*{re.escape(kw)}[^=]*\s*==+\s*(.*?)(?=\n==\s|\Z)',
            wikitext, re.DOTALL | re.IGNORECASE
        ):
            parts.append(m.group(1).strip())
    return "\n\n".join(parts)


def _get_funding_text(wikitext: str) -> str:
    """
    Try multiple strategies to extract text that contains funding data:
    1. Dedicated Funding section
    2. History / Finance / Business sections
    3. Full article (last resort)
    """
    # 1. Dedicated section
    text = _extract_section(wikitext, "Funding") or _extract_section(wikitext, "Investment")
    if text:
        return text

    # 2. Sections likely to contain funding info
    text = _extract_sections_containing(wikitext, ["funding", "finance", "investment", "history"])
    if text:
        return text

    # 3. Year-labelled sections (e.g. "2022–2023")
    text = _extract_sections_containing(wikitext, ["202"])  # matches 2020-2029
    if text:
        return text

    # 4. Full article (expensive but thorough)
    return wikitext


def _parse_infobox(wikitext: str) -> dict:
    """Extract key=value pairs from the first infobox using brace-depth-aware splitting."""
    m = re.search(r'\{\{Infobox\s+\w[^|]*\|', wikitext, re.IGNORECASE)
    if not m:
        return {}

    # Extract full infobox via brace counting (handles nested templates)
    start = m.start()
    depth, i = 0, start
    while i < len(wikitext):
        if wikitext[i:i+2] == '{{':
            depth += 1; i += 2
        elif wikitext[i:i+2] == '}}':
            depth -= 1; i += 2
            if depth == 0:
                break
        else:
            i += 1
    raw = wikitext[start:i]

    # Split on '|' at depth=1 (inside outer {{...}} but NOT inside nested templates/links).
    # depth starts at 0; outer {{ immediately brings it to 1; fields are at depth=1.
    def _split_at_fields(text: str) -> list[str]:
        parts, buf, d = [], [], 0
        j = 0
        while j < len(text):
            two = text[j:j+2]
            if two in ('{{', '[['):
                d += 1; buf.append(two); j += 2
            elif two in ('}}', ']]'):
                buf.append(two); j += 2
                d = max(0, d - 1)
            elif text[j] == '|' and d == 1:
                # Field separator: | at depth 1 (inside outer {{}} only)
                parts.append(''.join(buf).strip()); buf = []; j += 1
            else:
                buf.append(text[j]); j += 1
        if buf:
            parts.append(''.join(buf).strip())
        return parts

    segments = _split_at_fields(raw)
    result = {}
    for segment in segments[1:]:  # skip first segment (infobox name line)
        if '=' not in segment:
            continue
        eq_pos = segment.index('=')
        key   = segment[:eq_pos].strip().lower().replace(" ", "_").replace("-", "_")
        value = segment[eq_pos+1:].strip()
        if not key or not value:
            continue

        # Year from date template (e.g. {{Start date and age|2021}})
        year = _extract_year_from_template(value)
        if year:
            result[key] = year
            continue

        # List template: store as-is for special handling by caller
        if re.match(r'\{\{(?:Unbulleted list|Plain list|Flatlist|Hlist)\b', value, re.IGNORECASE):
            result[key] = value
            continue

        # Strip refs BEFORE cleaning to avoid ref-name fragments in output
        value = _strip_refs(value)
        value = _clean(value)
        if value:
            result[key] = value
    return result


def _extract_investors_from_text(text: str) -> list:
    """Pull wikilinked names that are plausibly investors."""
    raw_links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', text)
    investors = []
    for link in raw_links:
        name = link.split("#")[0].strip()
        if (name
                and len(name) > 3
                and not re.match(r'^\d', name)
                and not name.lower().startswith(("file:", "category:", "image:"))
                and name.lower() not in _NOT_INVESTOR):
            investors.append(name)
    return list(dict.fromkeys(investors))


# ---------------------------------------------------------------------------
# Core: sentence-level funding round extraction
# ---------------------------------------------------------------------------

_DOLLAR = re.compile(
    r'\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million|[bBmMkK])\b', re.IGNORECASE
)
_SERIES = re.compile(
    r'\b(Series\s+[A-Z]\+?(?:-[0-9])?|Seed|Pre-?[Ss]eed|Pre-?[Aa]|growth round)\b',
    re.IGNORECASE
)
_MONTH_YEAR = re.compile(
    r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)\b',
    re.IGNORECASE
)
_YEAR_ONLY = re.compile(r'\b(20\d\d)\b')

# "raised/received/secured/announced X" — this is the actual raise
# "committed" is intentionally excluded: covers compute/purchase commitments that aren't equity
_RAISE_VERB = re.compile(
    r'\b(raised?|received?|secured?|closed?\s+a|announcing?\s+a\s+\w+\s+round|announced?\s+\$|investing?|invested?)\s',
    re.IGNORECASE
)
# "valued at / valuation of / post-money valuation of X" — exclude these
_VALUATION_CTX = re.compile(
    r'\b(valuation|valued?\s+(?:at|the|it|company)|post-money|pre-money|valuing|estimate[ds]?|would\s+value)\b',
    re.IGNORECASE
)
# ARR / revenue / non-equity context — dollar amounts here are NOT equity funding rounds
_REVENUE_CTX = re.compile(
    r'\b(ARR|annual\s+recurring\s+revenue|annualiz[a-z]+\s+revenue|revenue|'
    r'monthly\s+recurring\s+revenue|MRR|subscription|run\s+rate|'
    r'compute\s+commitment|cloud\s+commitment|capacity\s+commitment|'
    r'government\s+contract|defense\s+contract|military\s+contract|'
    r'procurement\s+deal|partnership\s+deal|licensing\s+deal)\b',
    re.IGNORECASE
)


def _split_valuation_from_raise(sentence: str) -> str:
    """
    Return the portion of the sentence that describes what was RAISED,
    stripping out the valuation clause if present.
    Handles $, US$, USD, and bare numbers.
    """
    lower = sentence.lower()
    val_pos = None
    # These patterns mark where the valuation clause begins
    for pat in (
        r'(?:post-money\s+)?valuation\s+of\s+(?:us\$|\$|usd)',
        r'valued?\s+(?:at|near|above|around)\s+(?:us\$|\$|usd)?',
        r'post-money\s+valuation',
        r'pre-money\s+valuation',
        r'valuing\s+(?:the\s+)?(?:company|startup|firm|it)\b',
        r'at\s+a\s+(?:post-money\s+)?valuation',
        r'would\s+value\s+it',
        r'value\s+it\s+(?:near|at|around|above)',
        r'lifting\s+its\s+(?:post-money\s+|pre-money\s+|overall\s+)?valuation',
        r'implying\s+a\s+(?:total\s+)?valuation',
        r'setting\s+(?:a\s+|its\s+)?valuation',
    ):
        m = re.search(pat, lower)
        if m:
            val_pos = m.start() if val_pos is None else min(val_pos, m.start())

    if val_pos is not None:
        return sentence[:val_pos]
    return sentence


def _parse_funding_section(section_raw: str) -> list:
    """
    Parse individual funding rounds from the Funding section wikitext.
    Returns list of {announced_on, series, money_raised_usd, investors_mentioned}.
    """
    # Clean refs but keep wikilinks (for investor extraction)
    text = _strip_refs(section_raw)
    text = _strip_templates(text)

    rounds = []
    sentences = re.split(r'(?<=[.!?])\s+|\n+', text)

    for sentence in sentences:
        # Must contain a dollar amount
        if not _DOLLAR.search(sentence):
            continue

        has_raise     = bool(_RAISE_VERB.search(sentence))
        has_valuation = bool(_VALUATION_CTX.search(sentence))
        has_revenue   = bool(_REVENUE_CTX.search(sentence))

        # Skip sentences that are ONLY about valuation with no raise verb
        if has_valuation and not has_raise:
            continue

        # Skip ARR/revenue sentences unless there's also a clear raise signal
        if has_revenue and not has_raise:
            continue

        # Strip out the valuation clause to isolate the raised amount
        raise_clause = _split_valuation_from_raise(sentence) if has_valuation else sentence

        amounts = _DOLLAR.findall(raise_clause)
        if not amounts:
            # Fallback: try full sentence but prefer smallest amount
            # (smaller = raised; larger = valuation)
            all_amounts = _DOLLAR.findall(sentence)
            if not all_amounts:
                continue
            usd_vals = [(_usd(a, u), a, u) for a, u in all_amounts]
            usd_vals.sort()
            amounts = [(usd_vals[0][1], usd_vals[0][2])]

        primary_usd = max(_usd(a, u) for a, u in amounts)

        # Date
        date_str = None
        m_my = _MONTH_YEAR.search(sentence)
        if m_my:
            date_str = f"{m_my.group(2)}-{datetime.strptime(m_my.group(1), '%B').month:02d}"
        else:
            m_yr = _YEAR_ONLY.search(sentence)
            if m_yr:
                date_str = m_yr.group(1)

        # Series
        series = None
        m_rt = _SERIES.search(sentence)
        if m_rt:
            series = m_rt.group(1).replace("  ", " ").strip()

        # Investors from wikilinks in this sentence
        invs = _extract_investors_from_text(sentence)

        rounds.append({
            "announced_on": date_str,
            "series": series,
            "money_raised_usd": primary_usd,
            "investors_mentioned": invs,
        })

    # Deduplicate: same (date, amount) → merge investor lists
    merged = {}
    for rd in rounds:
        key = (rd["announced_on"], rd["money_raised_usd"])
        if key in merged:
            existing = merged[key]
            seen = set(existing["investors_mentioned"])
            for inv in rd["investors_mentioned"]:
                if inv not in seen:
                    existing["investors_mentioned"].append(inv)
                    seen.add(inv)
            if rd["series"] and not existing["series"]:
                existing["series"] = rd["series"]
        else:
            merged[key] = rd

    return list(merged.values())


# ---------------------------------------------------------------------------
# Wikipedia API helpers
# ---------------------------------------------------------------------------

def _fetch_wikitext(title: str) -> tuple[str, str]:
    resp = requests.get(
        WIKI_API,
        params={
            "action": "query", "prop": "revisions",
            "rvprop": "content", "rvslots": "main",
            "titles": title, "redirects": 1,
            "format": "json", "formatversion": "2",
        },
        headers={"User-Agent": WIKI_UA},
        timeout=15,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return "", title
    page = pages[0]
    canon    = page.get("title", title)
    wikitext = page["revisions"][0]["slots"]["main"]["content"]
    return wikitext, canon


def _search_wikipedia(name: str) -> str:
    resp = requests.get(
        WIKI_API,
        params={"action": "query", "list": "search", "srsearch": name, "srlimit": 5, "format": "json"},
        headers={"User-Agent": WIKI_UA},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("query", {}).get("search", [])
    if not results:
        return name
    name_lower = name.lower()
    for r in results:
        if r["title"].lower() == name_lower or name_lower in r["title"].lower():
            return r["title"]
    return results[0]["title"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape(company_name: str, wiki_title: str = None) -> dict:
    result = {
        "company_name": company_name,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "wikipedia",
        "wiki_title": None,
        "founded_on": None,
        "founders": [],
        "hq_location": None,
        "total_funding_usd": None,
        "num_funding_rounds": None,
        "last_funding_at": None,
        "funding_rounds": [],
        "investors": [],
        "tier1_investor_count": 0,
    }

    title = wiki_title or WIKI_TITLE_OVERRIDES.get(company_name) or company_name
    print(f"  [wikipedia] Fetching '{title}'...")

    wikitext, canon = _fetch_wikitext(title)
    if not wikitext:
        print(f"  [wikipedia] Not found — searching...")
        title = _search_wikipedia(company_name)
        wikitext, canon = _fetch_wikitext(title)

    if not wikitext:
        result["error"] = f"No Wikipedia article found for '{company_name}'"
        return result

    result["wiki_title"] = canon
    print(f"  [wikipedia] Got '{canon}' ({len(wikitext):,} chars)")

    # Infobox
    infobox = _parse_infobox(wikitext)
    founded_raw = (infobox.get("founded") or infobox.get("foundation")
                   or infobox.get("inception") or infobox.get("launch_date") or "")
    if founded_raw:
        yr = re.search(r'20\d\d|19\d\d', founded_raw)
        result["founded_on"] = yr.group(0) if yr else founded_raw[:20]

    founders_raw = infobox.get("founders") or infobox.get("founder") or ""
    if founders_raw:
        list_items = _extract_list_template(founders_raw)
        if list_items:
            result["founders"] = list_items[:8]
        else:
            # Handle separators: comma, semicolon, bullet •, middle-dot ·, newline
            result["founders"] = [f.strip() for f in re.split(r'[,;•·\n]', _clean(founders_raw)) if f.strip()][:8]

    hq_raw = (infobox.get("location") or infobox.get("headquarters")
              or infobox.get("hq_location_city") or "")
    if hq_raw:
        # Strip remaining templates
        hq_clean = _clean(hq_raw)
        result["hq_location"] = hq_clean[:100] if hq_clean else None

    # Funding data (try multiple section strategies)
    funding_text = _get_funding_text(wikitext)
    rounds = _parse_funding_section(funding_text)
    result["funding_rounds"] = rounds

    if rounds:
        result["total_funding_usd"] = sum(r["money_raised_usd"] for r in rounds if r["money_raised_usd"])
        result["num_funding_rounds"] = len(rounds)
        dated = [r for r in rounds if r.get("announced_on")]
        if dated:
            result["last_funding_at"] = max(r["announced_on"] for r in dated)

    # Aggregate investors
    seen: dict[str, dict] = {}
    for rd in rounds:
        for name in rd.get("investors_mentioned", []):
            if name not in seen:
                tier = "tier1" if name.lower() in TIER1_INVESTORS else "other"
                seen[name] = {"name": name, "tier": tier}

    result["investors"]            = list(seen.values())
    result["tier1_investor_count"] = sum(1 for v in seen.values() if v["tier"] == "tier1")

    total = result["total_funding_usd"]
    amt   = (f"${total/1e9:.1f}B" if total and total >= 1e9
             else (f"${total/1e6:.0f}M" if total else "unknown"))
    print(f"  [wikipedia] {len(rounds)} rounds | total {amt} | "
          f"{len(result['investors'])} investors ({result['tier1_investor_count']} tier1) | "
          f"founded {result['founded_on']}")
    return result


def write_output(company_name: str, data: dict) -> Path:
    safe_name = company_name.lower().replace(" ", "_").replace("/", "_")
    out_dir   = Path(__file__).parent.parent / "data" / "raw" / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file  = out_dir / "wiki.json"
    with open(out_file, "w") as f:
        json.dump(data, f, indent=2)
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Scrape Wikipedia for company funding signals")
    parser.add_argument("company", help="Company name")
    parser.add_argument("--title", default=None, help="Wikipedia article title override")
    args = parser.parse_args()

    data     = scrape(args.company, args.title)
    out_file = write_output(args.company, data)
    print(f"\nOutput: {out_file}")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
