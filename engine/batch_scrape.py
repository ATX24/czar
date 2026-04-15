"""
Batch scraper — reads data/companies.json and runs a given scraper across all companies.

Usage:
  python engine/batch_scrape.py github
  python engine/batch_scrape.py hn
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
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("github", "hn"):
        print("Usage: python batch_scrape.py [github|hn]")
        sys.exit(1)

    companies = load_companies()

    if sys.argv[1] == "github":
        run_github(companies)
    else:
        run_hn(companies)
