#!/usr/bin/env python3
"""
tt_login.py — one-time TikTok login for the cover-verification browser.

Launches a REAL Chrome window with a persistent profile. Log into TikTok in
that window, then close it. The LIVE session cookies are captured continuously
via the Playwright API (every ~5s once logged in) and written to
~/.hermes/tt_cookies.json — bypassing Chrome's on-disk cookie encryption,
which Chrome 152+ breaks under automation.

Usage:
    venv/bin/python tt_login.py          # opens the window; close when done
"""
import json
import os
import subprocess
import sys
import time

PROFILE = os.path.expanduser("~/.hermes/tt_browser_profile")
COOKIE_OUT = os.path.expanduser("~/.hermes/tt_cookies.json")


def save_cookies(ctx, out_path: str = None) -> int:
    """Write current tiktok cookies to the JSON file. Returns count saved."""
    out_path = out_path or COOKIE_OUT
    try:
        cookies = [c for c in ctx.cookies() if "tiktok" in c.get("domain", "")]
        with open(out_path, "w") as f:
            json.dump(cookies, f)
        return len(cookies)
    except Exception as e:
        print("cookie capture error:", e, flush=True)
        return 0


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", type=int, default=1, help="session number (1..5); each = separate login")
    args = ap.parse_args()
    n = args.session
    PROFILE = os.path.expanduser(f"~/.hermes/tt_browser_profile{n if n > 1 else ''}")
    COOKIE_OUT = os.path.expanduser(f"~/.hermes/tt_cookies{n if n > 1 else ''}.json")
    from playwright.sync_api import sync_playwright
    os.makedirs(PROFILE, exist_ok=True)
    # clear stale cookie capture
    if os.path.exists(COOKIE_OUT):
        os.remove(COOKIE_OUT)
    p = sync_playwright().start()
    print(f"Opening TikTok login window (session {n})...", flush=True)
    print("1) Log in to TikTok in that window  (QR code or phone/email).", flush=True)
    print("2) After login, CLOSE the window — your session is saved.", flush=True)
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
    page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
    closed = False
    page.on("close", lambda: closed or save_cookies(ctx, COOKIE_OUT))
    # capture cookies every 5s once the user is logged in; exit when the
    # window/page closes (poll in case the close event is missed)
    last_save = 0
    while True:
        time.sleep(3)
        try:
            if not ctx.pages:
                break
        except Exception:
            break
        # save every ~6s once session cookies exist
        try:
            sess = [c for c in ctx.cookies() if c.get("name") == "sessionid" and c.get("value")]
            if sess and time.time() - last_save > 6:
                n = save_cookies(ctx, COOKIE_OUT)
                last_save = time.time()
                print(f"  cookies saved ({n})", flush=True)
        except Exception:
            pass
        # if the page was closed by the user, give one final save and exit
        try:
            if page.is_closed():
                break
        except Exception:
            break
    # final capture before teardown
    n = save_cookies(ctx, COOKIE_OUT)
    ctx.close()
    p.stop()
    print(f"Done. {n} tiktok cookies -> {COOKIE_OUT}", flush=True)
    sys.exit(0 if n else 1)


if __name__ == "__main__":
    main()
