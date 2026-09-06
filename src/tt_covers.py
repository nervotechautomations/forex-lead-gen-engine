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
import os
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


def _load_tt_cookies() -> list:
    """Load the logged-in TikTok cookies: prefer the JSON captured at login
    time (Chrome 152+ refuses to persist cookies to disk under automation),
    fall back to reading the profile cookie DB."""
    import json as _json
    # 1) JSON capture (reliable)
    json_path = os.path.expanduser("~/.hermes/tt_cookies.json")
    if os.path.exists(json_path):
        try:
            cookies = _json.load(open(json_path))
            if cookies:
                norm = []
                for c in cookies:
                    if "tiktok" not in c.get("domain", ""):
                        continue
                    exp = c.get("expires", -1)
                    norm.append({
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", "").lstrip("."),
                        "path": c.get("path", "/"),
                        "expires": exp if exp and exp > 0 else 4102444800,
                        "secure": bool(c.get("secure", False)),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "sameSite": (c.get("sameSite") or "Lax").title(),
                    })
                if norm:
                    return norm
        except Exception:
            pass
    # 2) profile cookie DB fallback
    import sqlite3
    prof = os.path.expanduser("~/.hermes/tt_browser_profile/Default")
    db_path = os.path.join(prof, "Network", "Cookies")
    if not os.path.exists(db_path):
        db_path = os.path.join(prof, "Cookies")
    if not os.path.exists(db_path):
        return []
    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT host_key, name, value, path, expires_utc, is_secure FROM cookies "
        "WHERE host_key LIKE '%tiktok%' AND length(value) > 0").fetchall()
    db.close()
    cookies = []
    for host, name, value, path, exp, secure in rows:
        cookies.append({
            "name": name, "value": value, "domain": host.lstrip("."), "path": path,
            "expires": max(exp // 1000000 - 11644473600, 0), "secure": bool(secure),
            "httpOnly": False,
        })
    return cookies


def _proxy_pool() -> list:
    """Parse PROXY_URL from ~/.hermes/.env into (server, username, password) tuples."""
    env_path = os.path.expanduser("~/.hermes/.env")
    pool = []
    try:
        for line in open(env_path):
            if line.startswith("PROXY_URL="):
                for entry in line.strip().split("=", 1)[1].split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    # http://user:pass@host:port
                    rest = entry.split("//", 1)[1]
                    creds, hostport = rest.split("@", 1)
                    user, pw = creds.split(":", 1)
                    pool.append((f"http://{hostport}", user, pw))
                break
    except Exception:
        pass
    return pool


_PROXY_RI = [0]


def _launch(use_proxy: bool = True):
    """Launch Chrome with a FRESH temp profile + injected TikTok cookies.
    use_proxy=True: rotating residential proxy (dodges IP throttle).
    use_proxy=False: direct (dodges proxy-pool flags; home IP session).
    Returns (playwright, context, tmpdir)."""
    import tempfile
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    cookies = _load_tt_cookies()
    pool = _proxy_pool() if use_proxy else []
    tmpdir = tempfile.mkdtemp(prefix="ttverify-")
    kwargs = dict(
        channel="chrome", headless=True,
        viewport={"width": 1280, "height": 900}, locale="en-US",
        # never mock the keychain: real cookies must decrypt on disk
        ignore_default_args=["--use-mock-keychain"],
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    if pool:
        server, user, pw = pool[_PROXY_RI[0] % len(pool)]
        _PROXY_RI[0] += 1
        kwargs["proxy"] = {"server": server, "username": user, "password": pw}
    ctx = p.chromium.launch_persistent_context(tmpdir, **kwargs)
    if cookies:
        ctx.add_cookies(cookies)
    return p, ctx, tmpdir


def check_user(username: str, browser=None) -> dict:
    """Return verdict dict for one account. Each call uses a FRESH temp
    profile + rotating proxy IP + injected login cookies (throttle-dodge)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"username": username, "verdict": "error_no_playwright", "face": False}
    try:
        p, ctx, tmpdir = _launch(use_proxy=True)
        result = _probe(ctx, username, tmpdir)
        if not result.get("covers_found"):
            # proxy pool flagged -> retry direct (home IP session may be fresh)
            try:
                ctx.close()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            p2, ctx2, tmpdir2 = _launch(use_proxy=False)
            result = _probe(ctx2, username, tmpdir2)
            try:
                ctx2.close()
            except Exception:
                pass
            try:
                p2.stop()
            except Exception:
                pass
            shutil.rmtree(tmpdir2, ignore_errors=True)
        return result
    except Exception as e:
        try:
            ctx.close()
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass
        return {"username": username, "verdict": "error", "error": str(e)[:120], "face": False}


def _probe(ctx, username: str, tmpdir: str) -> dict:
    """Load the profile, collect covers + captions, run the face check."""
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    covers = []
    captions = set()

    def on_response(resp):
        if "/api/post/item_list/" in resp.url and resp.status == 200:
            try:
                data = resp.json()
                for it in (data.get("itemList") or []):
                    v = it.get("video") or {}
                    cover = v.get("cover") or v.get("dynamicCover")
                    if cover:
                        covers.append(cover)
                    cap = (it.get("desc") or "").strip()
                    if cap:
                        captions.add(cap[:200])
            except Exception:
                pass

    page.on("response", on_response)
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
        "captions": list(captions),
    }


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    json_out = "--json" in sys.argv
    if not args:
        print("usage: tt_covers.py [--json] <username> [<username> ...]")
        sys.exit(2)
    results = []
    for u in args:
        r = check_user(u)
        results.append(r)
        print(json.dumps(r) if json_out else f"{r['verdict']:20s} {u} (covers={r.get('covers_found', 0)})")
        time.sleep(2)
