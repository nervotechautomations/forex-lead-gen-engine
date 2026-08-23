# 🎯 Forex Influencer Lead-Gen Engine

An automated **lead-generation system** that discovers, verifies, and delivers qualified Spanish/English-speaking Forex trading influencers from Instagram & TikTok — running continuously via cron, texting batches of verified leads to a phone.

> Production-style pipeline: **discovery → verification → scoring → dedup → delivery**, with a self-healing state machine for rate limits.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A[Search Layer<br/>DDG + Brave keyword rotation<br/>66 keywords × 19 regions] --> B[Discovery<br/>extract handles<br/>+ post-snippet mining]
    B --> C[Verification Layer<br/>IG public API<br/>TikTok rehydration JSON<br/>proxy-aware routing]
    C --> D[Filter & Score<br/>followers 758–100k<br/>recency ≤90d<br/>engagement ≥1%<br/>ES/EN bio + forex keys<br/>futures excluded<br/>face/person-brand check]
    D --> E{Passed?}
    E -->|yes| F[Batch Builder<br/>holds in ready until 7]
    E -->|no| G[Rejection log<br/>with reason]
    F --> H[iMessage delivery<br/>@handle — followers — URL]
    H --> I[State file<br/>JSON dedup guard<br/>mark-sent-only-after-text]
    I --> A
```

## ✨ Features

| Capability | Detail |
|---|---|
| **Multi-engine discovery** | DuckDuckGo **+ Brave fallback** `site:instagram.com` rotation — **66 keywords × 19 regions** (1,254 combos) + post-snippet mining |
| **Dual-platform verification** | Instagram `web_profile_info` public API **and** TikTok rehydration JSON — real bio, follower count, engagement (never guessed data) |
| **Proxy-aware routing** | `PROXY_URL` env → round-robin pool; discovery + TikTok ride the proxy (kills search blocks), IG API stays direct (Webshare IPs are IG-flagged — documented in code) |
| **Face/person-brand filter** | OpenCV Haar face detection on avatar **OR** person-name display-name heuristic (accent-normalized, 100+ first names) — faceless chart/meme/logo pages rejected |
| **Quality filters** | 758 ≤ followers < 100k · last post ≤ 90 days · engagement ≥ 1% · Spanish **or** English · futures-only excluded (Topstep/NinjaTrader etc.) · private/spam/removed rejected |
| **Zero-duplicate guarantee** | JSON state machine with `sent` / `pending` / `ready` / `rejected`; leads marked sent **only after the text confirms** (no silent losses) |
| **Smart batching** | Partial batches held in `ready` (persisted), texts exactly 7 once accumulated — never spams 1–6 lead texts |
| **Cron automation** | Every 15 min; **silent when nothing new** (watchdog pattern), texts only on qualified findings |
| **Rate-limit resilience** | 4s request spacing, throttled accounts stay in `pending` and re-verify on later ticks (per-request luck, not a hard block) |

## 🧠 Search Strategy (keyword matrix)

High-intent query rotation — combinations of `site:instagram.com` + category keyword + region:

- **Category A — Prop Firm:** `fondeo de cuentas`, `cuentas fondeadas forex`, `empresa de fondeo`, `prueba de fondeo`, `desafío de fondeo`, `fases de fondeo`, `pasar el challenge`, `retiros de fondeo`, `payout fondeo`, `prop firm español`, `prop firm challenge`, `funded account`
- **Category B — General:** `señales de forex`, `señales gratis forex`, `estrategias de trading`, `análisis técnico forex`, `operar forex`, `broker de forex`, `trading de divisas`, `copytrading`, `grupo de trading`, `telegram trading`
- **Category C — Instruments:** `xauusd`, `oro trading`, `índices sintéticos`, `nasdaq trading`, `eurusd trading`, `day trading`, `gold signals`
- **Category D — Learning:** `curso de trading gratis`, `trading para principiantes`, `academia de trading`, `escuela de trading`, `trading desde cero`, `aprende trading`, `trading en español`, `psicotrading`, `gestor de capital`, `trading mentorship`
- **Category E — Lifestyle:** `trader rentable`, `vivir del trading`, `trader profesional`, `mentor de trading`, `trading en vivo`, `libertad financiera trading`, `trading lifestyle`, `mi vida como trader`
- **Regions (19):** España · México · Colombia · Argentina · Miami · Chile · Perú · Venezuela · República Dominicana · Ecuador · Guatemala · Costa Rica · Panamá · El Salvador · Bolivia · Uruguay · Paraguay · Puerto Rico · Honduras
- **Post-snippet mining:** "42 likes - `@username` on date" — post-level mentions are candidates too

## 🗂️ Project Layout

```
├── README.md
├── src/
│   ├── lead_hunter.py        # full pipeline: hunt → verify → filter → batch → deliver
│   ├── lead_verifier.py      # verification + filtering + dedup state machine
│   ├── tt_profile.py         # TikTok rehydration JSON parser (proxy-capable)
│   ├── face_check.py         # OpenCV Haar avatar face detection
│   └── search_hunter.py      # keyword rotation + handle extraction
├── config/
│   └── keyword_catalog.py    # 66-keyword × 19-region query matrix
├── data/
│   └── sample_output.json    # real anonymized delivery output
├── docs/
│   └── design_decisions.md   # why each filter/threshold exists
└── tests/
    └── test_core.py          # 11 filter-stack + extraction tests (stdlib only)
```

## 🚀 Quick Start

```bash
# 1. Install the imsg CLI (macOS iMessage delivery)
brew install steipete/tap/imsg

# 2. Configure recipient
export LEAD_PHONE="+1XXXXXXXXXX"

# 3. Verify a single candidate against the live APIs
python3 src/lead_hunter.py --check fondeapro

# 4. Run the full hunt → verify → batch → deliver cycle
python3 src/lead_hunter.py --run

# 5. Automate (cron every 15 min, silent when nothing new)
crontab -e
# */15 * * * * cd ~/forex-lead-gen-engine && /usr/bin/python3 src/lead_hunter.py --run
```

### 🌐 Proxy rotation (optional but recommended)

Instagram's public API throttles per-IP, and search engines block datacenter IPs.
Point the hunter at a **rotating residential pool** — each request rides a fresh IP:

```bash
# ~/.hermes/.env (auto-loaded by the hunter; no code changes needed)
# Single rotating gateway:
PROXY_URL=http://user:pass@gateway.provider.com:12345
# Or a comma-separated pool, round-robined per request:
PROXY_URL=http://u1:p1@host1:port1,http://u2:p2@host2:port2
```

Routing is deliberate: discovery + TikTok ride the proxy (search blocks vanish,
anti-bot walls bypassed), while IG's API stays direct — some residential
providers' IP ranges are pre-flagged by Instagram (documented in code), and the
direct home connection still has intermittent access windows.

### 🤖 Face detection (TikTok influencer verification)

```bash
# Requires opencv-python-headless in a venv:
python3 -m venv venv && venv/bin/pip install opencv-python-headless
# The hunter calls face_check.py automatically when verifying TikTok profiles.
```

Real creators with stylized avatars pass via the person-name heuristic
(accent-normalized, 100+ Spanish/English first names); brand pages like
"Forex Signals" or "Gold Trader" stay rejected.

## ⚖️ Ethics & Compliance

- **Public data only** — no login, no cookies, no private endpoints. Uses the same public profile data any visitor could see.
- **Rate-limited politely** — 4s request spacing, retry-with-backoff, never hammering.
- **No fabricated data** — every follower count / bio / engagement metric in the output comes from a live API response or search-index snippet, never invented.
- **No spam architecture** — dedup state prevents any profile from being contacted twice.
- **Respects platform intent** — verification uses public metadata; outreach itself is the user's responsibility and should follow each platform's policies.

## 📈 Results (real run)

- **135+ verified leads** delivered across 15 batches, zero duplicates
- **Dual-platform coverage** — IG (API) + TikTok (rehydration JSON + face verification)
- **Dead-account protection** — recency filter caught accounts 2–7 years inactive that a naive scraper would have shipped
- **Affiliate-pipeline operators** surfaced on purpose — prop-firm deal hubs, broker-verified mentors, signal funnels with referral links

---

*Demo of an automated intelligence pipeline: search strategy, data verification, quality scoring, state machines, face detection, and delivery automation.*
