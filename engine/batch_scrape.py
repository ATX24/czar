"""
Batch scraper — reads data/companies.json and runs a given scraper across all companies.

Usage:
  python engine/batch_scrape.py github
  python engine/batch_scrape.py hn
  python engine/batch_scrape.py crunchbase
  python engine/batch_scrape.py dealroom
  python engine/batch_scrape.py openvc
  python engine/batch_scrape.py funding       # crunchbase + dealroom + openvc in one pass
"""

import sys
import json
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import github_scraper
import hn_scraper
import crunchbase_scraper
import dealroom_scraper
import openvc_scraper
import wiki_scraper

# ---------------------------------------------------------------------------
# Explicit repo overrides where org/org pattern doesn't hold
# ---------------------------------------------------------------------------
GITHUB_REPO_OVERRIDES = {
    "Fly.io":            ("superfly", "flyctl"),         # main user-facing repo
    "Val Town":          ("val-town", "vt"),              # main CLI/SDK (134 stars)
    "Physical Intelligence": ("Physical-Intelligence", "openpi"),
}

# Companies confirmed to have no meaningful public GitHub presence
GITHUB_NO_PUBLIC_REPO = {
    "Bolt",        # bolt.new is fully closed
    "Cognition",   # cognition-ai org is empty/private
    "Tonic.ai",    # product is closed-source
    "Stainless",   # SDK tooling is private
    "Fivetran",    # data connectors are closed-source
}

# ---------------------------------------------------------------------------
# Companies where the name is a generic English word — use exact phrase matching
# to suppress noise (e.g. "render" matches WebGL tutorials, "sierra" matches
# Sierra Nevada, "lambda" matches AWS Lambda and lambda calculus)
# ---------------------------------------------------------------------------
HN_EXACT_PHRASE = {
    "Sierra",        # Sierra Nevada, Sierra Leone, Sierra Club
    "Render",        # rendering, WebGL, 3D render
    "Lambda",        # AWS Lambda, lambda calculus, Python lambda
    "Linear",        # linear algebra, linear regression
    "Runway",        # runway models, fashion runway
    "Groq",          # less generic but short
    "Clay",          # clay pottery
    "Vast",          # generic adjective
    "Depot",         # Home Depot, depot (logistics)
    "Wiz",           # wizard, wiz kid
    "Fal",           # uncommon but check
    "Arc Boat Company",  # "arc" alone too generic
    "Sorcerer",      # fantasy/gaming term
    "Oklo",          # short proper noun, less noise but be safe
    "Icarus",        # mythology
    "Hermeus",       # proper noun, should be ok but exact is safer
    "Hadrian",       # Roman emperor
    "Vast",          # generic
    "Sesame",        # Sesame Street
    "Suno",          # short, could match other things
    "Velontra",      # unique enough but small
}

# ---------------------------------------------------------------------------
# Aliases for ambiguous/short company names to reduce HN search noise
# ---------------------------------------------------------------------------
HN_ALIASES = {
    "Cursor":        ["Anysphere", "cursor.sh"],
    "Bolt":          ["bolt.new", "StackBlitz"],
    "Linear":        ["linear.app"],
    "Gamma":         ["gamma.app"],
    "Groq":          ["groq.com"],
    "Runway":        ["runwayml", "runway ml"],
    "Fal":           ["fal.ai"],
    "Sesame":        ["sesame ai"],
    "Suno":          ["suno.ai"],
    "Clay":          ["clay.com"],
    "Sierra":        ["sierra.ai", "sierra customer"],
    "Genspark":      ["genspark ai"],
    "Fireworks AI":  ["fireworks.ai"],
    "LMArena":       ["lm arena", "lmarena"],
    "Val Town":      ["val.town"],
    "Turso":         ["libSQL", "turso db"],
    "Neon":          ["neon database", "neon postgres"],
    "Depot":         ["depot.dev"],
    "Resend":        ["resend.com"],
    "Stainless":     ["stainless api"],
    "Tonic.ai":      ["tonic ai"],
    "Granola":       ["granola ai"],
    "Raycast":       ["raycast.com"],
    "Vanta":         ["vanta compliance"],
    "Ramp":          ["ramp.com", "ramp finance"],
    "Glean":         ["glean.com", "glean search"],
    "Harvey":        ["harvey ai", "harvey legal"],
    "Mercor":        ["mercor ai"],
    "Hebbia":        ["hebbia ai"],
    "Decagon":       ["decagon ai"],
    "Legora":        ["legora ai"],
    "7AI":           ["7 ai", "seven ai"],
    "Polymarket":    ["polymarket.com"],
    "Kalshi":        ["kalshi.com"],
    "Perplexity":    ["perplexity ai", "perplexity.ai"],
    "Cohere":        ["cohere ai"],
    "ElevenLabs":    ["eleven labs", "elevenlabs.io"],
    "Poolside":      ["poolside ai"],
    "Unconventional AI": ["unconventional ai"],
    "Hippocratic AI": ["hippocratic ai"],
    "Sakana AI":     ["sakana ai"],
    "Deepgram":      ["deepgram ai"],
    "Merge Labs":    ["merge labs bci"],
    "Physical Intelligence": ["pi robotics", "physical intelligence"],
    "CoreWeave":     ["coreweave gpu"],
    "Together AI":   ["together.ai"],
    "Lambda":        ["lambda labs", "lambdalabs"],
    "Gecko Robotics": ["gecko robotics"],
    "Skild AI":      ["skild ai"],
    "QuEra Computing": ["quera computing"],
    "Anduril":       ["anduril industries"],
    "Figure AI":     ["figure ai", "figure robotics"],
    "Agility Robotics": ["agility robotics", "digit robot"],
    "Shield AI":     ["shield ai", "hivemind"],
    "Relativity Space": ["relativity space", "terran r"],
    "Redwood Materials": ["redwood materials", "jb straubel"],
    "Helion Energy": ["helion energy", "helion fusion"],
}

# ---------------------------------------------------------------------------
# Load company list
# ---------------------------------------------------------------------------

def load_companies():
    path = ROOT / "data" / "companies.json"
    with open(path) as f:
        data = json.load(f)
    companies = []
    for cat_key, cat in data["categories"].items():
        for c in cat["companies"]:
            c["_category"] = cat_key
            companies.append(c)
    return companies


# ---------------------------------------------------------------------------
# GitHub batch
# ---------------------------------------------------------------------------

def run_github(companies):
    skipped, success, failed = [], [], []

    with_orgs = [c for c in companies if c.get("github_org")]
    print(f"\n=== GitHub Batch: {len(with_orgs)} companies with orgs ===\n")

    for i, company in enumerate(with_orgs, 1):
        name = company["name"]
        org  = company["github_org"]
        override = GITHUB_REPO_OVERRIDES.get(name)
        print(f"[{i}/{len(with_orgs)}] {name} ({org})")

        if name in GITHUB_NO_PUBLIC_REPO:
            skipped.append(name)
            print(f"  SKIP — no meaningful public GitHub repo\n")
            continue

        try:
            if override:
                data = github_scraper.scrape(name, override[0], override[1])
            else:
                data = github_scraper.scrape(name, org)
            github_scraper.validate(data)
            github_scraper.write_output(name, data)
            success.append(name)
            stars = data.get("stars", "?")
            gained = (data.get("star_trajectory_30d") or {}).get("stars_gained_30d")
            commits = (data.get("commit_velocity") or {}).get("commits_per_week_4w_avg")
            print(f"  OK — {stars:,} stars | +{gained} 30d | {commits} commits/wk\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")

        time.sleep(0.5)

    no_org = [c["name"] for c in companies if not c.get("github_org")]
    print(f"\n=== GitHub Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Failed  : {len(failed)}")
    print(f"  No org  : {len(no_org)} (skipped)")
    if failed:
        print(f"  Failures: {[n for n, _ in failed]}")
    return success, failed, no_org


# ---------------------------------------------------------------------------
# HN batch
# ---------------------------------------------------------------------------

def run_hn(companies):
    success, failed = [], []
    total = len(companies)
    print(f"\n=== HN Batch: {total} companies ===\n")

    for i, company in enumerate(companies, 1):
        name    = company["name"]
        aliases = HN_ALIASES.get(name, [])
        print(f"[{i}/{total}] {name}" + (f" + {aliases}" if aliases else ""))

        exact = name in HN_EXACT_PHRASE
        try:
            data = hn_scraper.scrape(name, aliases=aliases, exact_phrase=exact)
            hn_scraper.write_output(name, data)
            success.append(name)
            stories  = data.get("story_mention_count", 0)
            comments = data.get("comment_mention_count", 0)
            eng      = data.get("total_engagement_score", 0)
            print(f"  OK — {stories} stories | {comments} comments | eng {eng:.0f}\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")
            traceback.print_exc()

    print(f"\n=== HN Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Failed  : {len(failed)}")
    if failed:
        print(f"  Failures: {[n for n, _ in failed]}")
    return success, failed


# ---------------------------------------------------------------------------
# Crunchbase batch
# ---------------------------------------------------------------------------

# Slug overrides where name_to_slug() would produce the wrong result
CRUNCHBASE_SLUG_OVERRIDES = {
    "Cursor":            "anysphere",          # Cursor is made by Anysphere
    "Bolt":              "bolt-new",
    "Physical Intelligence": "physical-intelligence",
    "Fireworks AI":      "fireworks-ai",
    "Together AI":       "together-ai",
    "Figure AI":         "figure-ai",
    "Shield AI":         "shield-ai",
    "Skild AI":          "skild-ai",
    "Hippocratic AI":    "hippocratic-ai",
    "Sakana AI":         "sakana-ai",
    "7AI":               "7ai",
    "Merge Labs":        "merge-labs",
    "QuEra Computing":   "quera-computing",
    "Gecko Robotics":    "gecko-robotics",
    "Agility Robotics":  "agility-robotics",
    "Redwood Materials": "redwood-materials",
    "Relativity Space":  "relativity-space",
    "Helion Energy":     "helion-energy",
    "Arc Boat Company":  "arc-boat-company",
    "Val Town":          "val-town",
    "LMArena":           "lmarena",
    "Fal":               "fal-ai",
    "Tonic.ai":          "tonic-ai",
}


def run_crunchbase(companies):
    success, failed, skipped = [], [], []
    total = len(companies)
    print(f"\n=== Crunchbase Batch: {total} companies ===\n")

    for i, company in enumerate(companies, 1):
        name = company["name"]
        slug = CRUNCHBASE_SLUG_OVERRIDES.get(name)
        print(f"[{i}/{total}] {name}" + (f" (slug={slug})" if slug else ""))

        try:
            data = crunchbase_scraper.scrape(name, slug)
            crunchbase_scraper.write_output(name, data)

            if data.get("error"):
                failed.append((name, data["error"]))
                print(f"  FAIL — {data['error']}\n")
            else:
                success.append(name)
                total_f = data.get("total_funding_usd")
                rounds  = len(data.get("funding_rounds", []))
                invs    = len(data.get("investors", []))
                t1      = data.get("tier1_investor_count", 0)
                amt_str = f"${total_f/1e6:.0f}M" if total_f else "unknown"
                print(f"  OK — raised {amt_str} | {rounds} rounds | {invs} investors ({t1} tier1)\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")
            traceback.print_exc()

        time.sleep(1.5)  # be polite

    print(f"\n=== Crunchbase Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Failed  : {len(failed)}")
    if failed:
        print(f"  Failures: {[n for n, _ in failed]}")
    return success, failed


# ---------------------------------------------------------------------------
# Dealroom batch
# ---------------------------------------------------------------------------

DEALROOM_SLUG_OVERRIDES = {
    "Cursor":            "anysphere",
    "Physical Intelligence": "physical-intelligence",
    "Fireworks AI":      "fireworks-ai",
    "Together AI":       "together-ai",
    "Figure AI":         "figure-ai",
    "Shield AI":         "shield-ai",
    "Skild AI":          "skild-ai",
    "Val Town":          "val-town",
    "Arc Boat Company":  "arc-boat",
    "Tonic.ai":          "tonic-ai",
}


def run_dealroom(companies):
    success, failed = [], []
    total = len(companies)
    print(f"\n=== Dealroom Batch: {total} companies ===\n")

    for i, company in enumerate(companies, 1):
        name = company["name"]
        slug = DEALROOM_SLUG_OVERRIDES.get(name)
        print(f"[{i}/{total}] {name}")

        try:
            data = dealroom_scraper.scrape(name, slug)
            dealroom_scraper.write_output(name, data)

            if data.get("error"):
                failed.append((name, data["error"]))
                print(f"  FAIL — {data['error']}\n")
            else:
                success.append(name)
                total_f  = data.get("total_funding_usd")
                valuation = data.get("last_valuation_usd")
                amt_str  = f"${total_f/1e6:.0f}M" if total_f else "unknown"
                val_str  = f"${valuation/1e6:.0f}M" if valuation else "unknown"
                print(f"  OK — raised {amt_str} | valuation {val_str}\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")

        time.sleep(1.5)

    print(f"\n=== Dealroom Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Failed  : {len(failed)}")
    if failed:
        print(f"  Failures: {[n for n, _ in failed]}")
    return success, failed


# ---------------------------------------------------------------------------
# OpenVC batch
# ---------------------------------------------------------------------------

def run_openvc(companies):
    success, failed = [], []
    total = len(companies)
    print(f"\n=== OpenVC Batch: {total} companies ===\n")

    for i, company in enumerate(companies, 1):
        name = company["name"]
        print(f"[{i}/{total}] {name}")

        try:
            data = openvc_scraper.scrape(name)
            openvc_scraper.write_output(name, data)

            if data.get("error"):
                failed.append((name, data["error"]))
                print(f"  FAIL — {data['error']}\n")
            else:
                success.append(name)
                n_invs = data.get("openvc_investor_count", 0)
                print(f"  OK — {n_invs} investors found\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")

        time.sleep(1.0)

    print(f"\n=== OpenVC Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Failed  : {len(failed)}")
    if failed:
        print(f"  Failures: {[n for n, _ in failed]}")
    return success, failed


# ---------------------------------------------------------------------------
# Wikipedia batch
# ---------------------------------------------------------------------------

def run_wikipedia(companies):
    success, failed = [], []
    total = len(companies)
    print(f"\n=== Wikipedia Batch: {total} companies ===\n")

    for i, company in enumerate(companies, 1):
        name      = company["name"]
        wiki_title = wiki_scraper.WIKI_TITLE_OVERRIDES.get(name)
        print(f"[{i}/{total}] {name}" + (f" (title='{wiki_title}')" if wiki_title else ""))

        try:
            data = wiki_scraper.scrape(name, wiki_title)
            wiki_scraper.write_output(name, data)

            if data.get("error"):
                # Missing article is not a hard failure for small companies
                failed.append((name, data["error"]))
                print(f"  SKIP — {data['error']}\n")
            else:
                success.append(name)
                total_f = data.get("total_funding_usd")
                rounds  = len(data.get("funding_rounds", []))
                amt_str = (f"${total_f/1e9:.1f}B" if total_f and total_f >= 1e9
                           else (f"${total_f/1e6:.0f}M" if total_f else "unknown"))
                print(f"  OK — {rounds} rounds | total {amt_str} | "
                      f"founded {data.get('founded_on', '?')}\n")
        except Exception as e:
            failed.append((name, str(e)))
            print(f"  FAIL — {e}\n")

        time.sleep(0.5)   # Wikipedia has a generous rate limit

    print(f"\n=== Wikipedia Summary ===")
    print(f"  Success : {len(success)}")
    print(f"  Skipped : {sum(1 for _, e in failed if 'No Wikipedia' in e)}")
    print(f"  Failed  : {sum(1 for _, e in failed if 'No Wikipedia' not in e)}")
    return success, failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

VALID_SCRAPERS = ("github", "hn", "crunchbase", "dealroom", "openvc", "wikipedia", "funding")

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_SCRAPERS:
        print(f"Usage: python batch_scrape.py [{' | '.join(VALID_SCRAPERS)}]")
        sys.exit(1)

    companies = load_companies()
    cmd = sys.argv[1]

    if cmd == "github":
        run_github(companies)
    elif cmd == "hn":
        run_hn(companies)
    elif cmd == "crunchbase":
        run_crunchbase(companies)
    elif cmd == "dealroom":
        run_dealroom(companies)
    elif cmd == "openvc":
        run_openvc(companies)
    elif cmd == "wikipedia":
        run_wikipedia(companies)
    elif cmd == "funding":
        # Wikipedia first (free, reliable), then API-based if keys are set
        print("=== Funding pass: Wikipedia → Crunchbase → Dealroom ===")
        run_wikipedia(companies)
        run_crunchbase(companies)
        run_dealroom(companies)
