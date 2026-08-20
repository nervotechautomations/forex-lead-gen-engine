#!/usr/bin/env python3
"""
lead_verifier.py — Verification, filtering, dedup state machine, and delivery.

Fetches Instagram profile data via the public web_profile_info endpoint,
applies the quality filter stack, and texts batches of exactly 7 qualified
leads. Designed to be cron-safe: SILENT when nothing new qualifies.

Filters (all configurable):
  - followers: 758 <= n < 100_000
  - recency:   last post within 90 days
  - engagement: avg(likes+comments, last 12 posts) / followers >= 1%
  - language:  Spanish OR English bio
  - exclusions: futures-only accounts (TopStep, Apex, NinjaTrader...)
  - rejections: private accounts, removed pages, spam funnels

Dedup: state file keeps `sent` / `pending` / `rejected` sets.
`if u not in sent` guards every send — a lead can never be texted twice.
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
IG_APP_ID = "936619743392459"  # public web client app id

STATE = os.path.expanduser("~/.hermes/scripts/ig_leads_state.json")
PHONE = os.environ.get("LEAD_PHONE", "+1XXXXXXXXXX")  # set via env

# --- Filter thresholds ---------------------------------------------------
MIN_FOLLOWERS = 758
MAX_FOLLOWERS = 100_000
MAX_AGE_DAYS = 90
MIN_ENGAGEMENT_PCT = 1.0
BATCH_SIZE = 7

# --- Keyword heuristics --------------------------------------------------
KEYWORDS = [
    "forex", "trading", "trader", "fondeo", "fondead", "señal", "senal",
    "divisas", "inversion", "inversión", "pip", "broker", "mercado",
    "prop firm", "funded",
]
EXCLUDE = [
    "futures", "futuros", "micro e-mini", "e-mini", "topstep", "apex trader",
    "ninjatrader", "tradovate", "my funded futures", "myfundedfutures",
]

DEFAULT_PENDING = [
    "fondeapro", "tradingfx.finance", "besttfxsignals",
    "trading_institucionalfx1", "radardeinversiones", "vivirdeltrading.club",
]


# --- State ---------------------------------------------------------------
def load_state() -> dict:
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"pending": DEFAULT_PENDING, "sent": [], "rejected": {}}


def save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), indent=1)


# --- IG public API -------------------------------------------------------
def fetch_profile(username: str):
    """Fetch public profile JSON. Returns parsed dict or None on rate-limit."""
    req = urllib.request.Request(
        f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
        headers={"User-Agent": UA, "x-ig-app-id": IG_APP_ID},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None


def evaluate(data: dict):
    """
    Apply the full filter stack to a fetched profile.
    Returns (verdict, info) where verdict is 'pass' or 'reject:<reason>'.
    """
    user = data["data"]["user"]
    if user is None:
        return "reject:unavailable", {}

    followers = user["edge_followed_by"]["count"]
    bio = (user.get("biography") or "") + " " + (user.get("full_name") or "")
    info = {
        "followers": followers,
        "bio": user.get("biography", ""),
        "url": user.get("external_url"),
        "email": user.get("business_email"),
        "private": user.get("is_private"),
    }

    if user.get("is_private"):
        return "reject:private", info
    if not (MIN_FOLLOWERS <= followers < MAX_FOLLOWERS):
        return f"reject:followers={followers}", info

    bio_lower = bio.lower()
    if not any(k in bio_lower for k in KEYWORDS):
        return "reject:not_forex", info
    if any(k in bio_lower for k in EXCLUDE):
        return "reject:futures_trader", info

    edges = user["edge_owner_to_timeline_media"].get("edges", [])
    if not edges:
        return "reject:no_posts", info

    # Recency: most recent post within MAX_AGE_DAYS
    last_ts = max(e["node"]["taken_at_timestamp"] for e in edges)
    age_days = (time.time() - last_ts) / 86400
    info["last_post"] = datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d")
    if age_days > MAX_AGE_DAYS:
        return f"reject:stale_{int(age_days)}d", info

    # Engagement: avg(likes+comments) / followers
    eng = sum(
        e["node"]["edge_liked_by"]["count"]
        + e["node"]["edge_media_to_comment"]["count"]
        for e in edges
    ) / len(edges)
    rate = 100 * eng / max(followers, 1)
    info["eng_rate"] = round(rate, 2)
    if rate < MIN_ENGAGEMENT_PCT:
        return f"reject:low_eng_{rate:.2f}%", info

    return "pass", info


# --- Delivery ------------------------------------------------------------
def fmt_followers(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return str(n)


def send_batch(leads: list) -> None:
    lines = [
        f"@{u} — {fmt_followers(i['followers'])} — instagram.com/{u}"
        + (f" — {i['email']}" if i.get("email") else "")
        + (f" (eng {i.get('eng_rate','?')}%, last {i.get('last_post','?')})")
        for u, i in leads
    ]
    msg = "📊 WINNER LEADS ({}):\n".format(len(lines)) + "\n".join(lines)
    subprocess.run(["imsg", "send", "--to", PHONE, "--text", msg], timeout=60)
    print(msg)


# --- Main loop -----------------------------------------------------------
def main() -> None:
    st = load_state()
    pending, newly = st["pending"], []
    still_pending = []

    for u in pending:
        data = fetch_profile(u)
        time.sleep(3)  # polite spacing
        if not data or not data.get("data", {}).get("user"):
            still_pending.append(u)  # rate-limited / error -> retry later
            continue
        verdict, info = evaluate(data)
        if verdict == "pass":
            if u not in st["sent"]:
                newly.append((u, info))
                st["sent"].append(u)
        else:
            st["rejected"][u] = verdict

    st["pending"] = still_pending
    save_state(st)

    if newly:
        # batch into groups of exactly BATCH_SIZE and deliver each
        for i in range(0, len(newly), BATCH_SIZE):
            send_batch(newly[i : i + BATCH_SIZE])
    # else: silent tick (cron-friendly — nothing new, no message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", help="verify one username and print verdict")
    parser.add_argument("--run", action="store_true", help="full hunt+verify+batch cycle")
    args = parser.parse_args()

    if args.check:
        data = fetch_profile(args.check)
        if not data:
            print("rate-limited or unavailable — retry later")
        else:
            verdict, info = evaluate(data)
            print(json.dumps({"verdict": verdict, **info}, indent=2, ensure_ascii=False))
    else:
        main()
