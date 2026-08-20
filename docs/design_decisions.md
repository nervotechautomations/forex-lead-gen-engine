# Design decisions — why each filter exists (from real production runs)

## Follower floor: 758
Below ~750 followers, conversion value per outreach is negligible and most
accounts are hobbyist or dead. Hard floor keeps the batch quality high.

## Follower cap: 100k (raised from 20k)
Originally 20k (mid-tier creators). Raising to 100k unlocked 7 high-value
leads in one batch (86k, 60k, 57k, 52k, 52k, 32k, 29k) — accounts big
enough to have real audiences but small enough to answer DMs.

## Recency: last post ≤ 90 days
**Caught in production:** 2 of the first 4 API-verified leads had not posted
in 2–7 years (2019 and 2024 last posts). A naive scraper ships those;
they are dead leads. Recency is the single highest-value filter.

## Engagement: ≥ 1% (avg likes+comments of last 12 posts ÷ followers)
Filters ghost audiences and bought followers. A real 1k-follower account
averages 10+ interactions; a bought 50k account shows ~0.1%.

## Language: Spanish OR English
Original brief was Spanish-only (target market). English expansion added
later — TikTok's forex creator economy is largely English-speaking and
doubled the eligible pool.

## Futures exclusion
The client's product targets forex, not futures. Bios mentioning TopStep,
Apex, NinjaTrader, Tradovate, myfundedfutures, e-mini are rejected.
Lesson: a "prop firm" keyword match is NOT sufficient — prop firm content
is split ~50/50 between forex (FTMO-style) and futures (TopStep-style).

## Private-account rejection
A private profile with no visible bio/followers is unverifiable — spec
requires bio + follower visibility.

## Batch size: exactly 7
Delivery cadence chosen by the client ("don't stop till you send 7 more
each time") — keeps the text digestible and the pipeline throttled.

## Zero-duplicate architecture
State file `sent` set + `if u not in sent` guard before every send.
Also discovered: manual batches and cron runs both wrote state — overlap
(pending ∩ sent) caused wasted API calls, never duplicate texts. Cleanup
pass removes already-sent from pending.

## Rate-limit resilience
IG public API returns intermittent `"Asset ... has been deleted"` schema
errors and `"Please wait a few minutes"` — roughly 1-in-15 success during
throttle windows, and it is PER-REQUEST luck. Design: keep failed in
`pending`, re-verify each tick, never treat a throttle as a rejection.
A second path (logged-in browser preview) works when the API is fully
throttled.

## Silent cron ticks
Empty stdout = no text. The job only messages on genuinely new qualified
leads. This is the watchdog pattern: alert on signal, stay quiet on noise.
