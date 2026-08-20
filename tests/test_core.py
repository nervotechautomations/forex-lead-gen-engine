"""Core logic tests — run with: python3 tests/test_core.py (stdlib only)."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from lead_verifier import evaluate, MIN_FOLLOWERS, MAX_FOLLOWERS
from search_hunter import extract_handles


def mk_user(followers, bio="", private=False, posts=None):
    posts = posts if posts is not None else [
        {"node": {"taken_at_timestamp": int(time.time()),
                  "edge_liked_by": {"count": 95},
                  "edge_media_to_comment": {"count": 5}}}
        for _ in range(6)
    ]
    return {"data": {"user": {
        "edge_followed_by": {"count": followers},
        "biography": bio, "full_name": "", "is_private": private,
        "business_email": None, "external_url": None,
        "edge_owner_to_timeline_media": {"edges": posts}}}}


def test_filter_stack():
    cases = [
        # (name, payload, expected prefix)
        ("pass_1pct",        mk_user(10000, "Trader forex profesional, señales y mentoría"), "pass"),
        ("reject_over_cap",  mk_user(150000, "forex trader"), "reject:followers"),
        ("reject_under_floor", mk_user(500, "forex trader"), "reject:followers"),
        ("reject_futures",   mk_user(5000, "TopStep futures prop trader"), "reject:futures_trader"),
        ("reject_not_forex", mk_user(5000, "Fotógrafo de bodas 📸"), "reject:not_forex"),
        ("reject_private",   mk_user(5000, "forex", private=True), "reject:private"),
        ("reject_stale",     mk_user(5000, "forex trader", posts=[
            {"node": {"taken_at_timestamp": int(time.time()) - 200 * 86400,
                      "edge_liked_by": {"count": 50},
                      "edge_media_to_comment": {"count": 5}}} for _ in range(4)]),
         "reject:stale"),
        ("reject_low_eng",   mk_user(5000, "forex trader", posts=[
            {"node": {"taken_at_timestamp": int(time.time()),
                      "edge_liked_by": {"count": 1},
                      "edge_media_to_comment": {"count": 0}}} for _ in range(4)]),
         "reject:low_eng"),
        ("reject_no_posts",  mk_user(5000, "forex trader", posts=[]), "reject:no_posts"),
    ]
    for name, payload, expected in cases:
        verdict, _ = evaluate(payload)
        assert verdict.startswith(expected), f"{name}: got {verdict!r}, want {expected!r}"
        print(f"  ok {name}: {verdict}")


def test_snippet_mining():
    html = '''
    <a href="https://www.instagram.com/fondeapro/">FondeaPro</a>
    <a href="https://www.instagram.com/p/CcIaZyTqS2W/">post</a>
    <a href="https://www.instagram.com/jeantalerotrader/">Jean</a>
    42 likes, 27 comments - jd.garcia_19 on March 4, 2025
    2 likes, 0 comments - pasamos_tu_cuenta_de_fondeo_ on September 7
    1,208 likes, 14 comments - geudy on May 7
    '''
    handles = extract_handles(html)
    expected = {"fondeapro", "jeantalerotrader", "jd.garcia_19",
                "pasamos_tu_cuenta_de_fondeo_", "geudy"}
    assert expected <= handles, f"missing {expected - handles}; got {handles}"
    assert not (handles & {"p", "reel"}), "post URLs leaked into handles"
    print(f"  ok snippet mining: {sorted(handles)}")


def test_boundaries():
    assert MIN_FOLLOWERS == 758
    assert MAX_FOLLOWERS == 100_000
    assert MIN_FOLLOWERS < MAX_FOLLOWERS
    print("  ok filter bounds (758..100k)")


if __name__ == "__main__":
    for fn in (test_filter_stack, test_snippet_mining, test_boundaries):
        fn()
    print("\nALL TESTS PASS ✅")
