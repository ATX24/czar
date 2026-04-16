# czar — Startup Momentum Intelligence

> Continuously ranks 106 high-growth companies by real signal: HN engagement, GitHub velocity, funding rounds, product sentiment, and more.

---

## What It Does

czar has two independent systems inside one repo:

```
┌─────────────────────────────────────────────────────────────────┐
│                          czar                                    │
│                                                                  │
│   ┌──────────────────┐        ┌──────────────────────────────┐  │
│   │   engine/        │        │   pipeline/  +  frontend/    │  │
│   │                  │        │                              │  │
│   │  Score 106 known │        │  Discover unknown emerging   │  │
│   │  companies by    │        │  trends from Reddit + HN     │  │
│   │  momentum        │        │  in real-time                │  │
│   └──────────────────┘        └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## System 1 — Engine (Company Scoring)

Scrapes 7 data sources per company, then collapses everything into a **0–100 composite score**.

### Data Flow

```
  GitHub ──────────────┐
  Hacker News ─────────┤
  Reddit ──────────────┤
  Wikipedia ───────────┼──► data/raw/{company}/*.json ──► scorer.py ──► scores.json
  Crunchbase (API) ────┤
  Dealroom ────────────┤
  LinkedIn / Twitter ──┘   (stubs — scrapers ready)
```

### Scoring Dimensions

Each company gets scored across 6 dimensions, then weighted into a composite:

```
  Dimension            Weight   What it measures
  ─────────────────────────────────────────────────────────────────
  Organic Growth        20%     GitHub stars, 30d star velocity,
                                commit rate, HN story mentions,
                                HN engagement score, Reddit mentions

  Product Sentiment     20%     HN top-story points, comment depth,
                                Ask HN volume, Reddit score,
                                GitHub issues-to-stars ratio

  Funding Velocity      15%     Total raised (log scale), # rounds,
                                recency of last round,
                                tier-1 investor count, step-up multiples

  Revenue Proxies       15%     LinkedIn headcount, follower count
                                (proxy for team growth)

  Brand Signal          15%     Twitter/X followers, avg engagement
                                per tweet, content-type diversity

  Founder Signal        15%     HN karma of founders, quality of
                                founder submissions, mention count
  ─────────────────────────────────────────────────────────────────
  Composite             100%    Weighted sum × 100
```

> All sub-scores are normalized to [0, 1] before weighting. Log scales are used for
> skewed distributions (stars, funding) so that a $100M raise and a $10B raise don't
> map to 0.01 and 1.0 — they map to 0.80 and 1.0, which is more signal-preserving.

---

### Current Rankings (live snapshot)

```
 Rank  Company              Score   Organic  Sentiment  Funding
 ────────────────────────────────────────────────────────────────
   1   OpenAI               45.9     83.9      98.0      63.3
   2   SpaceX               43.2     83.3     100.0      43.3
   3   Anthropic            37.7     47.1      93.9      63.3
   4   Supabase             36.8     69.2      85.1      39.8
   5   Cursor               35.4     54.5      93.9      37.9
   6   7AI                  34.1     49.7      74.7      61.3
   7   Polymarket           34.0     52.1      72.8      60.0
   8   Perplexity           33.6     41.5      91.4      46.7
   9   Merge Labs           33.3     53.8      89.0      31.3
  10   Decagon              32.4     66.0      95.8       0.0
  11   Groq                 32.1     53.6      69.6      50.0
  12   Cohere               31.8     40.5      80.5      50.8
  13   Stripe               31.4     61.4      95.5       0.0
  14   Vercel               31.4     48.4      79.6      38.4
  15   Mercor               31.1     57.4      70.5      36.7
 ────────────────────────────────────────────────────────────────
 Note: Revenue Proxies / Brand / Founder Signal all 0.0 — LinkedIn
 and Twitter scrapers are not yet connected (stubs in place).
```

---

### Company Universe (106 companies, 5 categories)

```
  PLG Dev Tools (22)          Enterprise Software (22)
  ─────────────────           ────────────────────────
  Cursor · Lovable · Bolt     Databricks · Stripe · Vanta
  Windsurf · Gamma · Linear   Rippling · Ramp · Glean
  Raycast · Val Town · Neon   Harvey · Celonis · Fivetran
  Depot · Resend · Turso      Cohere · Hebbia · Decagon
  ... and more                ... and more

  AI / LLM Labs (22)          Hardware-Software Hybrids (20)
  ──────────────────          ──────────────────────────────
  OpenAI · Anthropic · xAI    CoreWeave · Groq · Saronic
  Mistral · Cohere · Together  Lambda · Fal · Fireworks AI
  ElevenLabs · Perplexity      Poolside · Suno · Runway
  Sakana · Deepgram · Groq     LMArena · Genspark
  ... and more                ... and more

  Pure Hardware / Defense (20)
  ────────────────────────────
  SpaceX · Anduril · Figure AI
  1X Technologies · Shield AI
  Relativity Space · Oklo
  Helion · Gecko Robotics
  ... and more
```

---

### Scrapers

| Scraper | Source | Status | Auth |
|---------|--------|--------|------|
| `hn_scraper.py` | Hacker News (Algolia API) | ✅ Working | None |
| `github_scraper.py` | GitHub REST API | ✅ Working | `GITHUB_TOKEN` (optional, raises rate limit) |
| `wiki_scraper.py` | Wikipedia Action API | ✅ Working | None |
| `reddit_scraper.py` | Reddit via PRAW | ✅ Working | `REDDIT_*` env vars |
| `crunchbase_scraper.py` | Crunchbase API | ⚠️ Needs key | `CRUNCHBASE_API_KEY` (free, 200 req/day) |
| `dealroom_scraper.py` | Dealroom | ⚠️ Partial | `DEALROOM_API_KEY` for full data |
| `linkedin_scraper.py` | LinkedIn | 🔲 Stub | Needs implementation |
| `twitter_scraper.py` | Twitter/X | 🔲 Stub | Needs implementation |

#### HN Matching — Noise Reduction

Many company names are generic words ("Lambda", "Linear", "Render", "Sierra"). The batch runner uses two techniques to reduce false matches:

```python
# Exact phrase search for ambiguous names
HN_EXACT_PHRASE = {"Sierra", "Render", "Lambda", "Linear", "Clay", ...}

# Aliases for companies whose HN presence lives under a different name
HN_ALIASES = {
    "Cursor":  ["Anysphere", "cursor.sh"],
    "Lambda":  ["lambda labs", "lambdalabs"],
    "Sierra":  ["sierra.ai", "sierra customer"],
    ...
}
```

#### Wikipedia Funding Parsing

The wiki scraper handles the most common Wikipedia funding-section patterns:

```
Raw wikitext sentence:
  "Anthropic raised $3.5 billion in a Series E round in March 2025,
   achieving a post-money valuation of $61.5 billion."

After valuation-clause stripping:
  "Anthropic raised $3.5 billion in a Series E round in March 2025,"
  → money_raised_usd: 3_500_000_000
  → series: "Series E"
  → announced_on: "2025-03"

Filtered out entirely:
  "...crossed $500 million ARR by June 2025"  (ARR ≠ equity raise)
  "...negotiating a round that would value it near $10 billion"  (valuation only)
  "...$750 million commitment with Microsoft Azure"  (compute deal)
```

---

### Running It

```bash
# Install dependencies
pip install -r requirements.txt

# Scrape a single source across all companies
python engine/batch_scrape.py hn
python engine/batch_scrape.py github
python engine/batch_scrape.py wikipedia

# Scrape all funding sources in one pass
python engine/batch_scrape.py funding    # wikipedia → crunchbase → dealroom

# Re-score everything
python engine/scorer.py --output data/scores.json

# Score a single company
python engine/scorer.py --company "Anthropic"

# Run a single scraper manually
python engine/wiki_scraper.py "Anthropic"
python engine/hn_scraper.py "Cursor"
python engine/github_scraper.py "Supabase" supabase
```

**Required `.env` keys:**

```env
# Optional — raises GitHub API rate limit from 60 to 5000 req/hr
GITHUB_TOKEN=ghp_...

# Reddit (for reddit_scraper)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=czar/1.0

# Crunchbase (free tier: 200 req/day — register at data.crunchbase.com)
CRUNCHBASE_API_KEY=...

# Dealroom (optional)
DEALROOM_API_KEY=...
```

---

## System 2 — Pipeline (Trend Detection)

A separate, general-purpose system that **discovers unknown emerging topics** from Reddit and HN — no predefined company list.

### Architecture

```
  ┌──────────────┐    ┌──────────────┐    ┌─────────────────────┐
  │  Collectors  │    │  Topic Model │    │   Velocity Scorer   │
  │              │    │              │    │                     │
  │  HN Firebase │───►│  BERTopic    │───►│  score = Δvolume    │
  │  Reddit PRAW │    │  (BERT emb.  │    │  not raw volume     │
  │              │    │  + HDBSCAN)  │    │                     │
  └──────────────┘    └──────────────┘    └──────────┬──────────┘
          │                                           │
          ▼                                           ▼
    DuckDB / Supabase                    ┌────────────────────┐
    (raw_posts table)                    │  Digest Generator  │
                                         │                    │
                                         │  Top 10 themes     │
                                         │  + LLM summaries   │
                                         │  (optional)        │
                                         └────────────────────┘
```

### Velocity vs. Volume

The key insight: **a topic growing from 5→50 posts/day ranks higher than one flat at 10,000**.

```
  Volume-based ranking           Velocity-based ranking
  ──────────────────             ──────────────────────
  1. JavaScript (10k/day)        1. New paper on X (5→50, z=3.1)
  2. Python (8k/day)             2. Tool Y just launched (2→30, z=2.8)
  3. AI (7k/day)                 3. Framework Z controversy (10→80, z=2.4)
  4. New paper on X (50/day) ◄── 4. AI (7k/day, flat)
  ...                            ...
```

The scorer computes a z-score against a 30-day baseline:

```
  velocity_score = (posts_last_24h - baseline_avg) / baseline_stddev

  If velocity_score > 2.0  →  inflection point detected
  Final score = recency_weight_24h × v_24h + recency_weight_7d × v_7d
              + inflection_bonus (if inflection)
```

### Running the Pipeline

```bash
# Collect + model + score + generate digest
python pipeline/scrape_multi_source.py

# Or run on a schedule (default: every 6 hours)
python pipeline/scheduler.py

# Push raw posts to Supabase
python pipeline/scrape_to_supabase.py

# Migrate existing DuckDB data to Supabase
python pipeline/migrate_to_supabase.py
```

---

## System 3 — Frontend Dashboard

React + TypeScript + Vite dashboard that reads from Supabase and visualizes the pipeline output.

```
  ┌────────────────────────────────────────┐
  │  czar  ✺                          ●   │
  │  ──────────────────────────────────── │
  │  [ Heatmap 12 ] [ Gravity 4 ] [ ↑ 3 ] │
  │                                        │
  │  Heatmap view                          │
  │  ─────────────────────────────────     │
  │  1. "llm inference"     ████████ 87    │
  │     velocity +340%  · reddit · 42 posts│
  │                                        │
  │  2. "cursor composer"   ███████  74    │
  │     velocity +180%  · hn · 18 posts    │
  │                                        │
  │  3. "openai o3"         ██████   61    │
  │     velocity +120%  · hn · 31 posts    │
  └────────────────────────────────────────┘
```

**Three views:**

| Tab | What it shows |
|-----|--------------|
| **Heatmap** | All discovered topics ranked by velocity score |
| **Gravity** | Topics where multiple "watched" influential accounts are all posting about the same thing simultaneously |
| **Inflections** | Topics that crossed the z-score threshold — sudden spikes |

Clustering happens **client-side** using Jaccard similarity on post term sets (no server round-trip):

```
  post A: "llm inference speed benchmark"
  post B: "inference benchmark for llms"
  shared terms: {llm, inference, benchmark} / total: 5 = 0.6 → same cluster ✓

  post A: "cursor composer feature"
  post C: "openai api pricing"
  shared terms: {} / total: 6 = 0.0 → different cluster ✓
```

### Running the Frontend

```bash
cd frontend
npm install
npm run dev       # localhost:5173

# Requires VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env
```

---

## Repo Structure

```
czar/
│
├── engine/                     # Company scoring system
│   ├── batch_scrape.py         # Run any scraper across all 106 companies
│   ├── scorer.py               # Weighted composite scorer (6 dimensions)
│   ├── hn_scraper.py           # Hacker News (Algolia API)
│   ├── github_scraper.py       # GitHub REST API
│   ├── wiki_scraper.py         # Wikipedia (free, no auth)
│   ├── crunchbase_scraper.py   # Crunchbase (API key required)
│   ├── dealroom_scraper.py     # Dealroom (partial)
│   ├── openvc_scraper.py       # OpenVC (stub)
│   ├── reddit_scraper.py       # Reddit via PRAW
│   ├── linkedin_scraper.py     # LinkedIn (stub)
│   ├── twitter_scraper.py      # Twitter/X (stub)
│   └── pitchbook_scraper.py    # Pitchbook (stub)
│
├── pipeline/                   # General trend detection
│   ├── collectors/
│   │   ├── hackernews_collector.py
│   │   └── reddit_collector.py
│   ├── analysis/
│   │   ├── topic_modeler.py    # BERTopic clustering
│   │   └── velocity_scorer.py  # z-score velocity scoring
│   ├── store/
│   │   ├── db.py               # DuckDB layer
│   │   └── models.py           # Pydantic models (Post, Topic, TopicScore)
│   ├── output/
│   │   ├── digest_generator.py # Weekly digest + optional LLM summaries
│   │   └── html_report.py      # HTML report output
│   ├── config.py               # All config in one place
│   ├── scheduler.py            # APScheduler loop
│   ├── scrape_multi_source.py  # One-shot collect → model → score
│   └── scrape_to_supabase.py   # Supabase-backed collection
│
├── frontend/                   # React dashboard
│   └── src/
│       ├── App.tsx             # Main app, Supabase data fetch
│       ├── lib/analyze.ts      # Client-side clustering + inflection detection
│       ├── components/
│       │   └── TopicCard.tsx
│       └── types.ts
│
├── data/
│   ├── companies.json          # The 106-company universe + metadata
│   ├── scores.json             # Latest composite scores
│   └── raw/                    # Scraped JSON per company (gitignored)
│       └── {company}/
│           ├── hn.json
│           ├── github.json
│           ├── wiki.json
│           ├── crunchbase.json
│           └── ...
│
├── supabase_schema.sql         # Supabase table definitions
└── requirements.txt
```

---

## What's Working vs. What's Next

```
  ✅  Done                          🔲  Next
  ──────────────────────────────    ────────────────────────────────
  HN scraper (exact phrase match)   LinkedIn scraper
  GitHub scraper (stars, velocity)  Twitter/X scraper
  Wikipedia funding parser          Pitchbook / Crunchbase API batch
  Batch runner (all sources)        Scheduled re-scoring (cron)
  6-dimension composite scorer      Frontend integration with scores
  Dealroom HTML metadata            Supabase → scores.json sync
  Pipeline: collect + model         Alert system (Slack / email)
  Pipeline: velocity scoring          when a company spikes
  Frontend: heatmap / gravity /
            inflections views
```
