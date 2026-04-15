# czar — Company Signal Intelligence Engine

Private equity / venture intelligence tool for scoring high-growth private companies across 6 signal dimensions.

## Overview

This repo contains an inference layer (`engine/`) that scrapes signals from GitHub, HN, Twitter/X, Reddit, Crunchbase, and LinkedIn, then scores companies on a 0–100 composite scale.

## Directory Structure

```
engine/               ← scrapers + scorer
  github_scraper.py   ← GitHub API: stars, commits, forks, contributor growth
  hn_scraper.py       ← HN Algolia API: founder history, company mentions
  twitter_scraper.py  ← X API v2: founder brand signals, content type ratio
  reddit_scraper.py   ← Reddit: subreddit mentions, founder account history
  crunchbase_scraper.py ← Crunchbase: funding rounds, investor tier, valuation step-ups
  linkedin_scraper.py ← LinkedIn/Proxycurl: headcount, early employee pedigree
  scorer.py           ← reads data/raw/ and scores companies across 6 dimensions

data/
  companies.json      ← full list of companies to analyze
  schema.json         ← target output schema for all scrapers
  raw/                ← one subfolder per company, populated by scrapers

other/
  README.md           ← this file
  requirements.txt    ← Python dependencies
```

## Setup

```bash
pip install -r other/requirements.txt
```

Copy `.env.example` to `.env` and fill in your API keys:

```
GITHUB_TOKEN=ghp_...
TWITTER_BEARER_TOKEN=AAAA...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
CRUNCHBASE_API_KEY=...
PROXYCURL_API_KEY=...
```

## Running Scrapers

### GitHub (fully implemented)

```bash
python engine/github_scraper.py "Cursor" getcursor
python engine/github_scraper.py "Supabase" supabase
python engine/github_scraper.py "Linear" linear
# Or specify a repo explicitly:
python engine/github_scraper.py "Supabase" supabase --repo supabase
```

Output: `data/raw/{company_name}/github.json`

### HN

```bash
python engine/hn_scraper.py "Cursor" --founders "Michael Truell" "Sualeh Asif"
```

### Twitter/X

```bash
python engine/twitter_scraper.py "Cursor" --company-handle cursor_ai --founders truell_michael
```

### Reddit

```bash
python engine/reddit_scraper.py "Cursor" --subreddits programming MachineLearning cursor
```

### Crunchbase

```bash
python engine/crunchbase_scraper.py "Cursor" anysphere
```

### LinkedIn (via Proxycurl)

```bash
python engine/linkedin_scraper.py "Cursor" "https://www.linkedin.com/company/anysphere-inc/"
```

## Scoring

```bash
# Score a specific company (after running scrapers):
python engine/scorer.py --company Cursor

# Score all companies with data:
python engine/scorer.py

# Write results to file:
python engine/scorer.py --output scores.json
```

## Scoring Dimensions

| Dimension | Weight | Signals |
|---|---|---|
| Organic Growth | 20% | GitHub stars/30d trajectory, commit velocity, HN mentions, Reddit velocity |
| Funding Velocity | 15% | Round recency, step-up multiples, tier-1 investor count, total raised |
| Revenue Proxies | 15% | LinkedIn headcount, follower growth |
| Product Sentiment | 20% | HN post scores, Reddit scores, GitHub issues/stars ratio |
| Brand Signal | 15% | Twitter followers, engagement rate, content type diversity |
| Founder Signal | 15% | HN founder mentions, founder LinkedIn presence |

Composite score = weighted sum × 100, range [0, 100].

## Company Universe

86 companies across 5 categories:
- PLG / Bottoms-Up Dev Tools (22)
- Enterprise Software (22)
- AI-Native / LLM / Labs (22)
- Hardware + Software Hybrids (20)
- Pure Hardware / Deep Tech / Defense (20)

See `data/companies.json` for the full list with GitHub orgs and metadata.

## Notes

- All scrapers write to `data/raw/{company_name}/{scraper}.json`
- Scraper outputs are validated against `data/schema.json`
- GitHub scraper is the only fully implemented scraper; others are stubs ready for API keys
- The HN scraper uses the free Algolia API (no key required)
- Reddit, Twitter, Crunchbase, LinkedIn all require API keys/tokens
