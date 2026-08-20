#!/usr/bin/env python3
"""
search_hunter.py — Keyword-rotation discovery layer.

Rotates `site:instagram.com` queries across a category keyword matrix and
optional regions, extracts candidate handles from result pages, and feeds
them into the pending queue for verification.

Search engines are intentionally hit politely (single queries, spaced)
to stay under rate limits; a blocked engine rotates to the next one.
"""
import re
import subprocess
import time
import urllib.parse

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

ENGINES = [
    "https://html.duckduckgo.com/html/?q={q}",
    "https://lite.duckduckgo.com/lite/?q={q}",
]

HANDLE_RE = re.compile(r"instagram\.com/([a-zA-Z0-9._]{2,30})/?")
POST_PATH = ("p", "reel", "tv", "popular", "stories", "explore")  # skip
SNIPPET_RE = re.compile(r"(\d+)\s+(?:likes|comments)[^@\n]*?(?:-\s*|@)([a-zA-Z0-9._]{2,30})\b")


def build_queries(categories: list, regions: list) -> list:
    """Cartesian product: site:instagram.com + keyword [+ region]."""
    queries = []
    for kw in categories:
        q = f'site:instagram.com "{kw}"'
        queries.append(q)
        for region in regions:
            queries.append(f'{q} {region}')
    return queries


def extract_handles(html: str) -> set:
    """Pull profile handles, skipping post URLs; also mine post snippets."""
    handles = set()
    for m in HANDLE_RE.finditer(html):
        handle = m.group(1)
        path = handle.split("/")[0]
        if path not in POST_PATH and len(path) > 1:
            handles.add(path)
    for m in SNIPPET_RE.finditer(html):
        handles.add(m.group(2))
    return handles


def search(query: str) -> str:
    for engine in ENGINES:
        url = engine.format(q=urllib.parse.quote(query))
        try:
            out = subprocess.run(
                ["curl", "-s", "-A", UA, url],
                capture_output=True, text=True, timeout=25,
            ).stdout
            if "anomaly" not in out and "captcha" not in out.lower():
                return out
        except Exception:
            continue
        time.sleep(8)  # polite backoff between engines
    return ""


def hunt(queries: list, max_per_query: int = 3) -> set:
    """Run query rotation, return union of discovered handles."""
    found: set = set()
    for q in queries:
        html = search(q)
        handles = extract_handles(html)
        found |= set(list(handles)[:max_per_query])
        print(f"[{len(found):>3}] {q} -> {len(handles)} handles")
        time.sleep(4)
    return found


if __name__ == "__main__":
    from config.keyword_catalog import CATEGORIES, REGIONS

    queries = build_queries(CATEGORIES, REGIONS)
    print(f"Running {len(queries)} queries...")
    for h in sorted(hunt(queries)):
        print("  candidate:", h)
