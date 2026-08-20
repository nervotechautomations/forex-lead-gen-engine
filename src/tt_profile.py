#!/usr/bin/env python3
"""TikTok profile parser — extracts profile data from the public rehydration JSON.
Usage: python3 tt_profile.py <username>"""
import json
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch_profile(username: str):
    req = urllib.request.Request(
        f"https://www.tiktok.com/@{username}",
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return None


def parse_profile(html: str) -> dict:
    if not html:
        return {}
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if not m:
        return {}
    try:
        d = json.loads(m.group(1))
        u = (d.get("__DEFAULT_SCOPE__", {})
             .get("webapp.user-detail", {})
             .get("userInfo", {})
             .get("user", {}))
        if not u:
            return {}
        info = {
            "username": u.get("uniqueId"),
            "full_name": u.get("nickname"),
            "bio": u.get("signature") or "",
            "private": u.get("privateAccount"),
            "verified": u.get("verified"),
        }
        # engagement signal: aggregate video stats if present
        ud = d.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {}).get("userInfo", {})
        stats = ud.get("stats", {})
        info["followers"] = stats.get("followerCount")
        info["following"] = stats.get("followingCount")
        info["posts"] = stats.get("videoCount")
        info["total_likes"] = stats.get("heartCount")
        info["avatar"] = u.get("avatarLarger")
        return info
    except Exception:
        return {}


if __name__ == "__main__":
    u = sys.argv[1]
    html = fetch_profile(u)
    info = parse_profile(html)
    print(json.dumps(info, ensure_ascii=False, indent=1) if info else "{}")
