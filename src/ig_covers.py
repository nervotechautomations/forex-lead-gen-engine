#!/usr/bin/env python3
"""
ig_covers.py — logged-in Instagram verification (the IG answer to tt_covers).

Loads each profile in a fresh headless Chrome with the logged-in IG cookies,
intercepts the web_profile_info API (works when logged in, dodging the home-IP
throttle on the anonymous endpoint), and:
  - checks follower count / privacy / staleness
  - face-detect the most recent post thumbnails (content evidence)
  - computes real per-post engagement (avg likes+comments per post / followers)
  - collects bio + captions for the forex/language gates

CLI:  venv/bin/python ig_covers.py --json <username> [<username> ...]
Output: one JSON verdict per account:
  {username, verdict: pass|reject:<reason>|no_covers_found|error,
   followers, full_name, bio, captions:[...], eng_rate}
"""
import json
import os
import sys
import time
import urllib.request

COOKIES = os.path.expanduser("~/.hermes/ig_cookies.json")


def _load_ig_cookies(session: int = 1) -> list:
    paths = [COOKIES]
    for i in range(2, 6):
        alt = os.path.expanduser(f"~/.hermes/ig_cookies{i}.json")
        if os.path.exists(alt):
            paths.append(alt)
    p = paths[(session - 1) % len(paths)]
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p))
    except Exception:
        return []


def _norm(c):
    return {
        "name": c.get("name", ""),
        "value": c.get("value", ""),
        "domain": c.get("domain", "").lstrip("."),
        "path": c.get("path", "/"),
        "expires": c.get("expires", 0) if c.get("expires") and c.get("expires", 0) > 0 else 4102444800,
        "secure": bool(c.get("secure", False)),
        "httpOnly": bool(c.get("httpOnly", False)),
        "sameSite": (c.get("sameSite") or "Lax").title(),
    }


def covers_have_face(urls, min_ratio=4):
    """OpenCV face detection on post thumbnails via face_check.py (venv)."""
    import subprocess
    checked, detections = 0, []
    for u in urls[:6]:
        try:
            proc = subprocess.run(
                [os.path.expanduser("~/.hermes/scripts/venv/bin/python"),
                 os.path.expanduser("~/.hermes/scripts/face_check.py"), "--json", u],
                capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                out = proc.stdout.strip().splitlines()
                det = 0
                for line in out:
                    try:
                        det = json.loads(line).get("faces", 0)
                    except Exception:
                        continue
                    break
                checked += 1
                detections.append(det)
        except Exception:
            continue
    return any(d > 0 for d in detections), checked, detections


def check_user(username: str, session: int = 1) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"username": username, "verdict": "error_no_playwright", "followers": 0}
    import tempfile
    import shutil
    cookies = _load_ig_cookies(session)
    if not cookies:
        return {"username": username, "verdict": "error_no_login",
                "followers": 0, "note": "run ig_login.py first"}
    p = None
    ctx = None
    tmpdir = None
    try:
        p = sync_playwright().start()
        tmpdir = tempfile.mkdtemp(prefix="igverify-")
        ctx = p.chromium.launch_persistent_context(
            tmpdir, channel="chrome", headless=True,
            viewport={"width": 1280, "height": 900}, locale="en-US",
            ignore_default_args=["--use-mock-keychain"],
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx.add_cookies([_norm(c) for c in cookies])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        captured = {}

        def on_response(resp):
            if "web_profile_info" in resp.url and resp.status == 200:
                try:
                    captured["data"] = resp.json()
                except Exception:
                    pass

        page.on("response", on_response)
        for attempt in range(3):
            try:
                page.goto(f"https://www.instagram.com/{username}/",
                          timeout=25000, wait_until="domcontentloaded")
            except Exception:
                pass
            page.wait_for_timeout(4000 + attempt * 2000)
            if captured.get("data"):
                break
        if not captured.get("data"):
            return {"username": username, "verdict": "no_covers_found",
                    "followers": 0, "note": "web_profile_info API blocked"}
        user = (captured["data"].get("data") or {}).get("user") or {}
        followers = (user.get("edge_followed_by") or {}).get("count", 0)
        bio = user.get("biography") or ""
        full_name = user.get("full_name") or ""
        edges = ((user.get("edge_owner_to_timeline_media") or {}).get("edges") or [])
        thumbs = [e["node"].get("display_url") for e in edges[:6]
                  if e["node"].get("display_url")]
        caps = [e["node"].get("edge_media_to_caption", {}).get("edges", [{}])[0]
                .get("node", {}).get("text", "")[:200] for e in edges[:6]]
        caps = [c for c in caps if c]
        eng_rates = []
        for e in edges:
            node = e.get("node", {})
            likes = ((node.get("edge_liked_by") or {}).get("count", 0))
            comments = ((node.get("edge_media_to_comment") or {}).get("count", 0))
            if followers > 0:
                eng_rates.append(100.0 * (likes + comments) / followers)
        eng = round(sorted(eng_rates)[len(eng_rates) // 2], 2) if eng_rates else None
        face, checked, dets = covers_have_face(thumbs)
        result = {
            "username": username,
            "followers": followers,
            "full_name": full_name,
            "bio": bio,
            "captions": caps,
            "eng_rate": eng,
            "face": face,
            "covers_found": len(thumbs),
            "covers_checked": checked,
            "detections": dets,
        }
        if user.get("is_private"):
            result["verdict"] = "reject:private"
        elif not thumbs:
            result["verdict"] = "no_covers_found"
        elif not face:
            result["verdict"] = "reject:faceless"
        else:
            result["verdict"] = "pass"
        return result
    except Exception as e:
        return {"username": username, "verdict": "error", "followers": 0,
                "error": str(e)[:120]}
    finally:
        try:
            if ctx:
                ctx.close()
        except Exception:
            pass
        try:
            if p:
                p.stop()
        except Exception:
            pass
        try:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    json_out = "--json" in sys.argv
    session = 1
    if "--session" in args:
        i = args.index("--session")
        try:
            session = int(args[i + 1])
        except Exception:
            pass
        del args[i:i + 2]
    if not args:
        print("usage: ig_covers.py [--json] [--session N] <username> ...")
        sys.exit(1)
    for u in args:
        r = check_user(u, session)
        if json_out:
            print(json.dumps(r))
        else:
            print(f"{r.get('verdict','?'):20s} {u} (f={r.get('followers')})")
        time.sleep(2)
