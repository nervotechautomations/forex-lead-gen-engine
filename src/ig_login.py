#!/usr/bin/env python3
"""
ig_login.py — one-time Instagram login for IG verification.

Launches a REAL Chrome window with a persistent profile. Log into Instagram in
that window, then close it. The LIVE session cookies are captured continuously
via the Playwright API and written to ~/.hermes/ig_cookies.json (bypassing
Chrome's broken on-disk cookie persistence under automation).

Usage:
    venv/bin/python ig_login.py           # session 1 (ig_cookies.json)
    venv/bin/python ig_login.py --session 2
"""
import argparse
import json
import os
import time

PROFILE_BASE = os.path.expanduser("~/.hermes/ig_browser_profile")
COOKIE_BASE = os.path.expanduser("~/.hermes/ig_cookies")


def save_cookies(ctx, out_path) -> int:
    try:
        cookies = [c for c in ctx.cookies() if "instagram" in c.get("domain", "")
                   or "cdninstagram" in c.get("domain", "")]
        with open(out_path, "w") as f:
            json.dump(cookies, f)
        return len(cookies)
    except Exception as e:
        print("cookie capture error:", e, flush=True)
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=int, default=1, help="session number (1..5)")
    args = ap.parse_args()
    n = args.session
    PROFILE = PROFILE_BASE + (str(n) if n > 1 else "")
    COOKIE_OUT = COOKIE_BASE + (str(n) if n > 1 else "") + ".json"
    from playwright.sync_api import sync_playwright
    os.makedirs(PROFILE, exist_ok=True)
    if os.path.exists(COOKIE_OUT):
        os.remove(COOKIE_OUT)
    p = sync_playwright().start()
    print(f"Opening Instagram login window (session {n})...", flush=True)
    print("1) Log in to Instagram (username/email or phone).", flush=True)
    print("2) When you see your feed, CLOSE the window.", flush=True)
    print(f"Profile: {PROFILE} -> {COOKIE_OUT}", flush=True)
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        channel="chrome",
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        ignore_default_args=["--use-mock-keychain"],
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
    page.on("close", lambda: save_cookies(ctx, COOKIE_OUT))
    last_save = 0
    while True:
        time.sleep(3)
        try:
            if not ctx.pages:
                break
        except Exception:
            break
        try:
            sess = [c for c in ctx.cookies()
                    if c.get("name") == "sessionid" and c.get("value")]
            if sess and time.time() - last_save > 6:
                n_saved = save_cookies(ctx, COOKIE_OUT)
                last_save = time.time()
                print(f"  cookies saved ({n_saved})", flush=True)
        except Exception:
            pass
        try:
            if page.is_closed():
                break
        except Exception:
            break
    n_saved = save_cookies(ctx, COOKIE_OUT)
    ctx.close()
    p.stop()
    print(f"Done. {n_saved} IG cookies -> {COOKIE_OUT}", flush=True)
    raise SystemExit(0 if n_saved else 1)


if __name__ == "__main__":
    main()
