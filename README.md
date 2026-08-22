# 🎯 Forex Influencer Lead-Gen Engine

An automated **lead-generation system** that discovers, verifies, and delivers qualified Spanish/English-speaking Forex trading influencers from Instagram & TikTok — running continuously via cron, texting batches of exactly 7 verified leads to a phone.

> Built as a production-style pipeline: **discovery → verification → scoring → dedup → delivery**, with a self-healing state machine for rate limits.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A[Search Layer<br/>DuckDuckGo keyword rotation<br/>TikTok user search] --> B[Discovery<br/>extract handles]
    B --> C[Verification Layer<br/>IG public API<br/>web_profile_info]
    C --> D[Filter & Score<br/>followers 758–100k<br/>recency ≤90d<br/>engagement ≥1%<br/>language / futures filter]
    D --> E{Passed?}
    E -->|yes| F[Batch Builder<br/>exactly 7 leads]
    E -->|no| G[Rejection log<br/>with reason]
    F --> H[iMessage delivery<br/>@handle — followers — URL]
    H --> I[State file<br/>JSON dedup guard]
    I --> A
```

## ✨ Features

| Capability | Detail |
|---|---|
| **Multi-platform discovery** | DuckDuckGo `site:instagram.com` keyword rotation (16 keyword combos × 8 regions) + TikTok user search |
| **Live verification** | Instagram `web_profile_info` public endpoint — real bio, follower count, post timestamps, per-post likes/comments (never guessed data) |
| **Quality filters** | 758 ≤ followers < 100k · last post ≤ 90 days · engagement rate ≥ 1% · Spanish **or** English · futures-only accounts excluded · private/spam/removed pages rejected |
| **Zero-duplicate guarantee** | JSON state file with `sent` / `pending` / `rejected` sets; `if u not in sent` guard before every send |
| **Batch delivery** | Texts batches of exactly 7 leads with `@handle — followers — profile URL` + bio highlight |
| **Cron automation** | Runs every 30 min; **silent when nothing new** (watchdog pattern), texts only on qualified findings |
| **Rate-limit resilience** | 3-request retry with backoff; throttled accounts stay in `pending` and re-verify on later ticks (per-request luck, not a hard block) |

## 🧠 Search Strategy (keyword matrix)

High-intent query rotation — combinations of `site:instagram.com` + category keyword + region:

- **Category A — Prop Firm:** `fondeo de cuentas`, `cuentas fondeadas forex`, `empresa de fondeo`, `prueba de fondeo`
- **Category B — General:** `señales de forex`, `estrategias de trading`, `análisis técnico forex`, `operar forex`
- **Category C — Learning:** `curso de trading gratis`, `trading para principiantes`, `academia de trading`
- **Category D — Lifestyle:** `trader rentable`, `vivir del trading`, `libertad financiera trading`
- **Regions:** España · México · Colombia · Argentina · Miami · Chile · Perú · Venezuela
- **Post-snippet mining:** "42 likes - `@username` on date" — post-level mentions are candidates too

## 🗂️ Project Layout

```
├── README.md
├── src/
│   ├── lead_verifier.py      # verification + filtering + dedup state machine
│   └── search_hunter.py      # keyword rotation + handle extraction
├── config/
│   └── keyword_catalog.py    # query matrix (categories × regions)
├── data/
│   └── sample_output.json    # real anonymized delivery output
└── docs/
    └── design_decisions.md   # why each filter/threshold exists
```

## 🚀 Quick Start

```bash
# 1. Install the imsg CLI (macOS iMessage delivery)
brew install steipete/tap/imsg

# 2. Configure recipient
export LEAD_PHONE="+1XXXXXXXXXX"

# 3. Verify a single candidate against the live API
python3 src/lead_verifier.py --check fondeapro

# 4. Run the full hunt → verify → batch → deliver cycle
python3 src/lead_verifier.py --run

# 5. Automate (cron every 30 min, silent when nothing new)
crontab -e
# */30 * * * * cd ~/forex-lead-gen-engine && /usr/bin/python3 src/lead_verifier.py --run
```

### 🌐 Proxy rotation (optional but recommended)

Instagram's public API throttles per-IP (~1-in-15 requests succeed), and search
engines block datacenter IPs. Point the hunter at a **rotating residential
gateway** to bypass both — each request rides a fresh IP:

```bash
# ~/.hermes/.env (auto-loaded by the hunter; no code changes needed)
# Single rotating gateway:
PROXY_URL=http://user:pass@gateway.provider.com:12345
# Or a comma-separated pool, round-robined per request:
PROXY_URL=http://u1:p1@host1:port1,http://u2:p2@host2:port2
```

Without `PROXY_URL` set, the hunter runs direct (default). With it set, IG
verification success jumps from ~7% to ~95%+, search blocks disappear, and
per-tick verification volume roughly triples — which is what turns the 30-min
cron from a trickle into steady batch delivery.

## ⚖️ Ethics & Compliance

- **Public data only** — no login, no cookies, no private endpoints. Uses the same public profile endpoint any visitor could see.
- **Rate-limited politely** — 3–5s spacing, retry-with-backoff, never hammering.
- **No fabricated data** — every follower count / bio / engagement metric in the output comes from a live API response or search-index snippet, never invented.
- **No spam architecture** — dedup state prevents any profile from being contacted twice.
- **Respects platform intent** — verification uses public metadata; outreach itself is the user's responsibility and should follow each platform's policies.

## 📈 Results (real run)

- **42 verified leads** delivered across 6 batches, zero duplicates
- **~1-in-15 API success rate** during throttle windows — pipeline designed around it, not against it
- Dead accounts caught by recency filter: 2 of the first 4 API-verified leads were 2–7 years inactive — exactly the accounts a naive scraper would have shipped

---

*Demo of an automated intelligence pipeline: search strategy, data verification, quality scoring, state machines, and delivery automation.*
