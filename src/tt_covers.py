#!/usr/bin/env python3
"""
tt_covers.py — Playwright-based TikTok face-content verification.

Loads a TikTok profile in a real (headless) Chromium browser, extracts the
video cover images from the profile grid, downloads a sample, and runs OpenCV
face detection on them. A face in ANY cover = the creator shows their face in
content (the user's "face-content influencer" bar).

Avatar-based detection is deliberately NOT used: calibration showed signals
pages use real-photo avatars, so only video-content evidence counts.

Usage:
    venv/bin/python tt_covers.py <username> [<username> ...]
    venv/bin/python tt_covers.py --json <username>

Exit: 0 always (verdicts printed per account). "--json" prints JSON lines.
"""
import json
import sys
import time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MAX_COVERS = 4          # how many covers to face-detect
COVER_SAMPLE = 6        # how many candidate imgs to pull from the grid


def _fetch(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def extract_cover_urls(page) -> list:
    """Pull video-cover img srcs from the profile grid, avatar excluded."""
    urls = []
    try:
        # TikTok profile grid items expose cover <img>s
        imgs = page.query_selector_all('div[data-e2e="user-post-item"] img')
        for img in imgs:
            src = img.get_attribute("src") or ""
            if src and "tiktokcdn" in src:
                urls.append(src)
    except Exception:
        pass
    if not urls:
        try:
            # fallback: any tiktokcdn img, minus the avatar (cropcenter/avatar style)
            imgs = page.query_selector_all("img")
            for img in imgs:
                src = img.get_attribute("src") or ""
                if ("tiktokcdn" in src and "~tplv" in src
                        and "avatar" not in src and "cropcenter" not in src):
                    urls.append(src)
        except Exception:
            pass
    # dedupe, keep insertion order
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:COVER_SAMPLE]


def covers_have_face(urls: list, min_ratio: int = 4) -> dict:
    """Face-detect each cover. Returns {face: bool, checked: n, detections: [...]}"""
    import cv2
    import numpy as np
    frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
    checked, detections = 0, []
    for u in urls[:MAX_COVERS]:
        try:
            raw = np.frombuffer(_fetch(u), dtype=np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            h, w = gray.shape
            min_side = max(24, min(h, w) // min_ratio)
            n = 0
            for cascade in (frontal, profile):
                n += len(cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side)))
            checked += 1
            detections.append(n)
        except Exception:
            continue
    return {"face": any(d > 0 for d in detections), "checked": checked, "detections": detections}


def _launch(browser=None):
    """Launch Chrome (real binary), preferring the logged-in persistent profile."""
    from playwright.sync_api import sync_playwright
    import os
    profile = os.path.expanduser("~/.hermes/tt_browser_profile")
    p = sync_playwright().start()
    if os.path.isdir(profile) and os.listdir(profile):
        # logged-in session exists -> headless with the same cookies
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chrome", headless=True,
            viewport={"width": 1280, "height": 900}, locale="en-US",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        return p, ctx
    # no session yet -> throwaway headless
    b = p.chromium.launch(headless=True, channel="chrome",
                          args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    return p, b


def check_user(username: str, browser=None) -> dict:
    """Return verdict dict for one account. Pass a shared browser/context to reuse it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"username": username, "verdict": "error_no_playwright", "face": False}
    own = False
    if browser is None:
        p, browser = _launch()
        own = True
    try:
        if hasattr(browser, "new_context"):  # plain Browser -> make a context
            ctx = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        else:  # persistent context -> use as-is (already has cookies)
            ctx = browser
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        covers = []

        def on_response(resp):
            if "/api/post/item_list/" in resp.url and resp.status == 200:
                try:
                    data = resp.json()
                    for it in (data.get("itemList") or []):
                        v = it.get("video") or {}
                        cover = v.get("cover") or v.get("dynamicCover")
                        if cover:
                            covers.append(cover)
                except Exception:
                    pass

        page.on("response", on_response)
        # retry: TikTok intermittently serves empty item_list under rapid loads
        for attempt in range(3):
            try:
                page.goto(f"https://www.tiktok.com/@{username}", timeout=25000,
                          wait_until="domcontentloaded")
            except Exception:
                pass
            page.wait_for_timeout(4000 + attempt * 1500)
            for _ in range(4):
                page.mouse.wheel(0, 800)
                page.wait_for_timeout(900)
            if covers:
                break
        if own:  # single-shot: close everything; shared: caller owns lifecycle
            ctx.close()
            try:
                browser.close()
            except Exception:
                pass
            p.stop()

        if not covers:
            return {"username": username, "verdict": "no_covers_found",
                    "face": False, "covers_found": 0, "covers_checked": 0, "detections": []}
        seen, unique = set(), []
        for c in covers:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        result = covers_have_face(unique)
        return {
            "username": username,
            "verdict": "face_content" if result["face"] else "no_face_content",
            "face": result["face"],
            "covers_found": len(unique),
            "covers_checked": result["checked"],
            "detections": result["detections"],
        }
    except Exception as e:
        try:
            ctx.close()
        except Exception:
            pass
        return {"username": username, "verdict": "error", "error": str(e)[:120], "face": False}
    finally:
        if own:
            try:
                browser.close()
            except Exception:
                pass
            p.stop()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    json_out = "--json" in sys.argv
    if not args:
        print("usage: tt_covers.py [--json] <username> [<username> ...]")
        sys.exit(2)
    try:
        p, browser = _launch()
    except Exception as e:
        print(json.dumps([{"username": a, "verdict": "error_launch", "error": str(e)[:120], "face": False} for a in args]))
        sys.exit(1)
    results = []
    for u in args:
        r = check_user(u, browser=browser)
        results.append(r)
        print(json.dumps(r) if json_out else f"{r['verdict']:20s} {u} (covers={r.get('covers_found', 0)})")
        time.sleep(2.5)
    # close whatever _launch gave us (persistent context or Browser)
    try:
        browser.close()
    except Exception:
        try:
            browser.contexts[0].close()
        except Exception:
            pass
    p.stop()
