#!/usr/bin/env python3
"""
tt_login.py — one-time TikTok login for the cover-verification browser.

Launches a REAL Chrome window with a persistent profile. Log into TikTok in
that window, then close it. The session is saved in the profile directory and
reused by tt_covers.py (which runs headless with the same profile).

Usage:
    venv/bin/python tt_login.py          # opens the window; close when done
"""
import os
import sys

PROFILE = os.path.expanduser("~/.hermes/tt_browser_profile")

def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(PROFILE, exist_ok=True)
    p = sync_playwright().start()
    print("Opening TikTok in a real Chrome window (headful).")
    print("1) Log in to TikTok in that window  (QR code or phone/email).")
    print("2) After login, CLOSE the window — your session is saved.")
    print("Profile:", PROFILE)
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        channel="chrome",
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
    # wait until the window is closed by the user
    try:
        while ctx.pages:
            import time
            time.sleep(1)
    except Exception:
        pass
    ctx.close()
    p.stop()
    print("Session saved. tt_covers.py will now use the logged-in profile.")


if __name__ == "__main__":
    main()
