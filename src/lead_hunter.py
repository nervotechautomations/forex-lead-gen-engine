#!/usr/bin/env python3
"""
ig_lead_hunter.py — Fully autonomous IG+TikTok Forex lead hunter.

Runs the entire loop without an LLM:
  1. HUNT    — DuckDuckGo (html + lite) query rotation over the keyword
               catalog x regions; extracts IG + TikTok handles.
  2. VERIFY  — IG via public web_profile_info API; TikTok via the public
               rehydration JSON (followers, bio, post count, total likes).
  3. FILTER  — 758 <= followers < 100k, Spanish/English bio, forex-related,
               not private, futures-only excluded, engagement proxy >= 1%.
  4. DELIVER — text batches of exactly 7 via imsg, dedup via state file.

Cron-safe: silent when nothing new qualifies.
"""
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from tt_profile import fetch_profile as tt_fetch, parse_profile as tt_parse  # noqa: E402

FACE_CHECK_PY = os.path.join(HERE, "venv", "bin", "python")
FACE_CHECK_SCRIPT = os.path.join(HERE, "face_check.py")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
IG_APP_ID = "936619743392459"
VENV_PY = os.path.join(HERE, "venv", "bin", "python")
FACE_CHECK_PY = os.path.join(HERE, "venv", "bin", "python")  # interpreter for face_check.py
STATE = os.path.join(HERE, "ig_leads_state.json")
PHONE = os.environ.get("LEAD_PHONE", "+17864522224")

# --- Proxy rotation support -------------------------------------------------
# Set PROXY_URL to a rotating residential gateway, e.g.:
#   http://user:pass@geo.iproyal.com:12321  (session-rotating gateway)
# or a pool of proxies separated by commas:
#   http://u:p@host1:port,http://u:p@host2:port
# Each request picks the next proxy (round-robin) when a pool is given.
# The value is read from ~/.hermes/.env (auto-loaded below) or the env.
def _load_dotenv():
    """Minimal .env loader — no dependencies."""
    env_path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv()
PROXY_URL = os.environ.get("PROXY_URL", "")
PROXIES = [p.strip() for p in PROXY_URL.split(",") if p.strip()]


def proxy_opener():
    """Build a urllib opener that round-robins through the configured proxies.
    Returns None when no proxy is configured (direct connection)."""
    if not PROXIES:
        return None
    idx = getattr(proxy_opener, "idx", 0)
    p = PROXIES[idx % len(PROXIES)]
    proxy_opener.idx = idx + 1
    handler = urllib.request.ProxyHandler({
        "http": p, "https": p,
    })
    return urllib.request.build_opener(handler)

def tt_fetch_proxy(username: str) -> str:
    """Fetch a TikTok profile — proxy first (fresh IP avoids anti-bot walls),
    fall back to direct."""
    opener = proxy_opener()
    if opener:
        try:
            body = tt_fetch(username, opener=opener)
            if body and '"webapp.user-detail"' in body:
                return body
        except Exception:
            pass
        time.sleep(2)
    try:
        return tt_fetch(username)
    except Exception:
        return ""


def tt_parse_proxy(html: str) -> dict:
    return tt_parse(html)


def verify_account(u: str, cover_budget: list = None) -> tuple:
    """IG API (direct) with post-thumbnail face gate; TikTok with cover gate.
    Returns (verdict, info): 'retry' means unverifiable this tick (throttled)
    -> caller keeps the account in pending.
    cover_budget: optional shared list; when non-empty, decrement per cover
    check and skip (return 'retry') once exhausted."""
    data = ig_profile(u)
    if data and data.get("data", {}).get("user"):
        return evaluate_ig(data)
    pinfo = tt_parse_proxy(tt_fetch_proxy(u))
    if pinfo:
        verdict, info = evaluate_tt(pinfo)
        if verdict != "pass":
            return verdict, info
        # final gate: cover-based face verification (authoritative)
        if cover_budget is not None:
            if cover_budget and cover_budget[0] <= 0:
                return "retry", None  # cover budget spent -> next tick
            cover_budget[0] -= 1
        cover, captions = cover_face_verdict(u)
        if cover == "pass":
            # content-level market check: reject stock/crypto/non-ES-EN content
            cc = caption_forex_check(captions)
            if cc in ("reject:stocks", "reject:crypto"):
                return "reject:not_forex", None
            if cc == "reject:other_language":
                return "reject:other_language", None
            if cc == "no_evidence":
                # no forex/stock/crypto markers in content: require forex
                # evidence in bio, else the account is unproven (e.g. trucking,
                # lifestyle, generic money pages)
                bio_blob = ((info.get("bio") or "") + " " + (info.get("full_name") or "")).lower()
                if not any(k in bio_blob for k in FX_KEYS):
                    return "reject:not_forex", None
            return "pass", info
        if cover == "reject:faceless":
            return "reject:faceless", None
        return "retry", None  # throttled/wall -> keep in pending
    return "fetch_failed", None


MIN_F, MAX_F, MIN_ENG, BATCH = 758, 100_000, 1.0, 7
# how many candidates to verify per tick — higher = faster batch accumulation,
# but more API pressure (keep 4s spacing to limit ban risk)
VERIFY_PER_TICK = 10
# TikTok cover checks are expensive AND throttle the logged-in session after
# ~2-3 loads. Cap per tick; accounts that need covers wait for a later tick.
COVER_CHECKS_PER_TICK = 2

KEYWORDS = [
    # --- Prop firm / funding (core) ---
    "fondeo de cuentas", "cuentas fondeadas forex", "empresa de fondeo",
    "prueba de fondeo", "desafío de fondeo", "desafio de fondeo",
    "fases de fondeo", "pasar el challenge", "retiros de fondeo",
    "payout fondeo", "cuenta fondeada", "prop firm español",
    "prop firm challenge", "funded account", "funded trader",
    # --- General forex ---
    "señales de forex", "señales gratis forex", "senales forex",
    "estrategias de trading", "análisis técnico forex", "analisis tecnico",
    "operar forex", "broker de forex", "trading de divisas",
    "copytrading", "copy trading", "grupo de trading", "telegram trading",
    # --- Instruments / markets ---
    "xauusd", "oro trading", "trading de oro", "indices sinteticos",
    "índices sintéticos", "sintéticos trading", "nasdaq trading",
    "eurusd trading", "day trading", "day trader", "gold signals",
    # --- Learning / beginner ---
    "curso de trading gratis", "trading para principiantes",
    "academia de trading", "escuela de trading", "clases de trading",
    "trading desde cero", "aprende trading", "aprender a hacer trading",
    "trading en español", "psicotrading", "gestion de riesgo trading",
    "gestor de capital", "asesor financiero trading",
    "trading mentorship", "forex education", "forex signals",
    # --- Lifestyle / aspirational ---
    "trader rentable", "vivir del trading", "trader profesional",
    "mentor de trading", "trading en vivo", "forex mentor",
    "libertad financiera trading", "trading lifestyle", "mi vida como trader",
    "trading community", "forex community",
]
REGIONS = ["España", "México", "Colombia", "Argentina", "Miami", "Chile", "Perú", "Venezuela",
           "República Dominicana", "Ecuador", "Guatemala", "Costa Rica", "Panamá",
           "El Salvador", "Bolivia", "Uruguay", "Paraguay", "Puerto Rico", "Honduras"]

BIO_KEYS = ["forex", "trading", "trader", "fondeo", "fondead", "señal", "senal",
            "divisas", "inversion", "inversión", "pip", "broker", "mercado",
            "prop firm", "funded", "xauusd", "mt4", "cfd", "oro", "sintetico",
            "sintético", "nasdaq", "eurusd", "gold", "payout", "challenge",
            "copy", "day trading", "psicotrading"]
FUTURES = ["futures", "futuros", "topstep", "apex", "ninjatrader", "tradovate",
           "myfundedfutures", "e-mini"]
# non-es/en indicator words (common on spam/scam accounts in other languages)
OTHER_LANG = ["giao dịch", "kiến thức", "đồng hành", "je suis", "je vais", " vous ", "chaque",
              "saya ", "belajar", "seputar", "tôi", "محترف", "تعلم", "vàng",
              "negozio", "apprendi",
              # German
              "aktien", "aktienmarkt", "lerne", "geld", "verdienen", "kostenlos",
              "tradingview", "chartanalyse", "diese", "einfache", "tricks",
              # Italian
              "imparo", "operare", "sognare", "inizia", "gratuitamente", "rimani",
              "amore", "fino alla fine",
              "educação", "pesquisa", "mercado financeiro", "comunidade", "alunos",
              "estou", "dinheiro", "precisa", "mensagem", "esperança", "treinados",
              "aprenda", "investimentos",
              # French
              "gagner", "apprendre", "argent", "trading en ligne", "vous apprend",
              "formez", "devenir"]
# stock/indices-only markers (not forex) — NOTE: generic "indices/index" NOT
# included: "índices sintéticos" (Deriv synthetics) is a forex-adjacent niche
STOCK_KEYS = ["accion", "acciones", "bolsa", "stocks", "stock ", "nasdaq", "sp500",
              "s&p", "etf", "nyse", "dow jones", "value investing",
              "trade de valor", "aktien", "buy hold", "chartanalyse", "dividend",
              "portfolio", "cartera"]
# crypto-only markers
CRYPTO_KEYS = ["crypto", "cripto", "bitcoin", "btc", "eth ", "ethereum", "binance", "bybit",
               "mexc", "solana", "usdt", "altcoin", "memecoin", "web3"]
# explicit forex markers (bio or captions)
FX_KEYS = ["forex", " fx", "xauusd", "eurusd", "gbpusd", "usdjpy", "divisa", "divisas",
           "pares", "pip", "pips", "mt4", "mt5", "fondeo", "fondeada", "fondeado",
           "sintetico", "sintéticos", "oro trading", "trading de oro", "gold trading",
           "broker", "tradingforex", "forextips", "trading forex"]

HANDLE_RE = re.compile(r"(?:instagram\.com|tiktok\.com/@)/([a-zA-Z0-9._]{2,30})/?")
SNIPPET_RE = re.compile(r"(\d+)\s+(?:likes|comments)[^@\n]*?(?:-\s*|@)([a-zA-Z0-9._]{2,30})\b")
POST_PATHS = {"p", "reel", "tv", "popular", "stories", "explore"}


# ---------------------------------------------------------------- state --
def load_state() -> dict:
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"pending": [], "sent": [], "rejected": {}, "qidx": 0}


def save_state(st: dict) -> None:
    json.dump(st, open(STATE, "w"), indent=1)


# ----------------------------------------------------------------- hunt --
def ddg(query: str) -> str:
    """Try DuckDuckGo, then Brave — both via curl (proxy-aware)."""
    opener = proxy_opener()
    engines = (
        "https://html.duckduckgo.com/html/?q={q}",
        "https://lite.duckduckgo.com/lite/?q={q}",
        "https://search.brave.com/search?q={q}",
    )
    for url_t in engines:
        url = url_t.format(q=urllib.parse.quote(query))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            if opener:
                with opener.open(req, timeout=20) as r:
                    body = r.read().decode("utf-8", "replace")
            else:
                with urllib.request.urlopen(req, timeout=20) as r:
                    body = r.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        if body:
            # accept the page if it actually yields handles; engine boilerplate
            # ("robot", "captcha") only matters when nothing was extracted
            if extract_handles(body):
                return body
            low = body.lower()
            if "anomaly" in low or "captcha" in low or "no results" in low:
                pass  # genuinely blocked/empty -> try next engine
            else:
                return body
        time.sleep(6)
    return ""


def extract_handles(html: str) -> set:
    handles = set()
    for m in HANDLE_RE.finditer(html):
        h = m.group(1)
        if h.split("/")[0] not in POST_PATHS:
            handles.add(h)
    for m in SNIPPET_RE.finditer(html):
        handles.add(m.group(2))
    return handles


# -------------------------------------------------------------- verify --
def ig_profile(username: str):
    """IG public API — DIRECT connection only. Webshare residential IPs are
    pre-flagged by Instagram (HTTP 429), so routing through the proxy here
    guarantees failure; the home IP still has intermittent access windows."""
    req = urllib.request.Request(
        f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
        headers={"User-Agent": UA, "x-ig-app-id": IG_APP_ID})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None


def evaluate_ig(data: dict):
    user = data["data"]["user"]
    if user is None:
        return "reject:unavailable", {}
    followers = user["edge_followed_by"]["count"]
    bio = (user.get("biography") or "") + " " + (user.get("full_name") or "")
    info = {"followers": followers, "bio": user.get("biography", ""),
            "url": user.get("external_url"), "email": user.get("business_email"),
            "platform": "instagram",
            "full_name": user.get("full_name") or "",
            "avatar": user.get("profile_pic_url_hd") or user.get("profile_pic_url")}
    if user.get("is_private"):
        return "reject:private", info
    if not (MIN_F <= followers < MAX_F):
        return f"reject:followers={followers}", info
    v = check_lang_and_topic(bio)
    if v != "ok":
        return v, info
    edges = user["edge_owner_to_timeline_media"].get("edges", [])
    if not edges:
        return "reject:no_posts", info
    last_ts = max(e["node"]["taken_at_timestamp"] for e in edges)
    if (time.time() - last_ts) / 86400 > 90:
        return "reject:stale", info
    # FACE GATE: face-detect the most recent post thumbnails (the IG
    # equivalent of TikTok cover verification — content evidence, not avatar).
    thumbs = [e["node"].get("display_url") for e in edges[:4] if e["node"].get("display_url")]
    if thumbs and not any_thumb_has_face(thumbs):
        return "reject:faceless", info
    eng = sum(e["node"]["edge_liked_by"]["count"] + e["node"]["edge_media_to_comment"]["count"]
              for e in edges) / len(edges)
    rate = 100 * eng / max(followers, 1)
    info["eng_rate"] = round(rate, 2)
    if rate < MIN_ENG:
        return "reject:low_eng", info
    return "pass", info


def evaluate_tt(info: dict):
    followers = info.get("followers") or 0
    bio = (info.get("bio") or "") + " " + (info.get("full_name") or "")
    if info.get("private"):
        return "reject:private", info
    if not (MIN_F <= followers < MAX_F):
        return f"reject:followers={followers}", info
    v = check_lang_and_topic(bio)
    if v != "ok":
        return v, info
    posts = info.get("posts") or 0
    if posts == 0:
        return "reject:no_posts", info
    # NOTE: face gate is NOT here — cover_face_verdict runs in verify_account
    # as the final gate, only for candidates that pass all cheap filters
    # (browser time is expensive and TikTok throttles).
    # engagement proxy: avg likes per video / followers (loose, uses lifetime totals)
    avg_likes = (info.get("total_likes") or 0) / posts
    rate = 100 * avg_likes / followers
    info["eng_rate"] = round(rate, 2)
    if rate < MIN_ENG:
        return "reject:low_eng", info
    return "pass", info


def any_thumb_has_face(thumb_urls: list) -> bool:
    """Face-detect each post thumbnail via the venv face_check (any face = pass)."""
    for u in thumb_urls:
        try:
            proc = subprocess.run(
                [VENV_PY, FACE_CHECK_PY, "--json", u],
                capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                return True
        except Exception:
            continue
    return False


def has_face_avatar(avatar_url: str) -> bool:
    """Run OpenCV Haar face detection on the avatar via the venv interpreter."""
    if not avatar_url:
        return False
    try:
        proc = subprocess.run(
            [FACE_CHECK_PY, FACE_CHECK_SCRIPT, "--json", avatar_url],
            capture_output=True, text=True, timeout=25,
        )
        if proc.returncode == 0:
            return True
        # exit 1 = clean 'no face'; parse json anyway for robustness
        try:
            return json.loads(proc.stdout).get("face") is True
        except Exception:
            return False
    except Exception:
        return False


# Common Spanish + English first names — used as a person-brand fallback so
# real creators with stylized/logoless avatars still pass, while pure brand
# pages ("Forex Signals", "Gold Trader", "Trading Academy") stay rejected.
FIRST_NAMES = {
    # Spanish/LatAm
    "juan", "carlos", "jose", "pedro", "luis", "javier", "diego", "fernando",
    "andres", "alejandro", "manuel", "david", "daniel", "miguel", "antonio",
    "francisco", "jorge", "sergio", "mario", "pablo", "marco", "leo", "tony",
    "kenzo", "izzy", "joaco", "sonia", "adriana", "cristian", "martin",
    "emilio", "raul", "gabriel", "ricardo", "oscar", "victor", "julio",
    "gerard", "jonathan", "geudy", "yael", "yonaiker", "frank", "jean",
    "beker", "nebz", "derek", "sean", "kay", "gabriel", "mateo", "thomas",
    "fatima", "sofia", "valentina", "camila", "lucia", "paula", "elena",
    "isabel", "carmen", "rosa", "patricia", "veronica", "alejandra", "paulina",
    "daniela", "fernanda", "natalia", "karla", "mariana", "valeria",
    "antonella", "milagros", "rocio", "belen", "agustina", "julieta", "melina",
    "candela", "damian", "matias", "nicolas", "facundo", "leandro", "gaston",
    "sebastian", "rodrigo", "bruno", "agustin", "franco", "lucas",
    "emiliano", "liliana", "esteban", "ismael", "mauricio", "ernesto",
    "arturo", "hector", "alberto", "benjamin", "alexis", "leonel", "isaac",
    "edgar", "roberto", "alfredo", "paola", "denisse", "marta", "claudia",
    "irene", "silvia", "norma", "graciela", "beatriz", "gloria", "leticia",
    "constanza", "ignacio", "salvador", "federico", "hernan", "julian",
    "marcos", "german", "tomas", "santiago", "felipe", "juanjo", "manolo",
    # English
    "james", "john", "michael", "robert", "william", "jason", "kevin",
    "brian", "eric", "justin", "brandon", "tyler", "jordan", "cody", "tanner",
    "sydney", "brittany", "ashley", "jennifer", "amanda", "stephanie",
    "nicole", "heather", "michelle", "rebecca", "melissa", "kelly", "tiffany",
    "vanessa", "destiny", "morgan", "hannah", "megan", "lauren", "kayla",
    "jasmine", "samantha", "chelsea", "sierra", "brooklyn", "madison",
    # English
    "katrina", "sarah", "emily", "jessica", "laura", "maria", "ana", "sandra",
    "grace", "chantel", "kasper", "virgil", "niki", "samuel", "alli", "sodeeq",
    "greg", "will", "david", "harsh", "mohammed", "ali", "omar", "ryan",
    "chris", "alex", "sam", "jake", "liam", "noah", "olivia", "emma",
    "ava", "mia", "sophia", "isabella", "mason", "logan", "elijah",
}
BRAND_WORDS = {
    "forex", "trading", "trader", "traders", "academy", "academia", "signals",
    "señales", "signal", "gold", "xauusd", "fx", "prop", "firm", "funded",
    "funding", "club", "group", "team", "pro", "official", "real", "master",
    "queen", "king", "life", "lifestyle", "tips", "education", "mentor",
    "coach", "broker", "pips", "market", "mercado", "divisas", "capital",
    "capital", "profit", "income", "investor", "inversion", "management",
    "community", "comunidad", "channel", "vlogs", "gratis", "free", "bot",
}


def looks_like_person(full_name: str) -> bool:
    """Heuristic: does the display name contain a real person's first name?
    STRICT: a known first name is required. Brand/topic names like
    'TradingWithDinero', 'SEÑALES_GOLD', 'PUERTO TRADE' or 'ForexSignals.com'
    contain no first name -> rejected. Face-avatar detection is the other
    accepted path (see has_face_or_person)."""
    if not full_name:
        return False
    low = unicodedata.normalize("NFKD", full_name.lower())
    low = "".join(c for c in low if not unicodedata.combining(c))  # strip accents
    words = [w.strip(" .,-•·|[]()🌟📈📉💹💰🔹🔸_") for w in low.split()]
    words = [w for w in words if w]
    # handle single-token "name.surname" handles: split on dots/underscores
    if len(words) == 1:
        words = [w.strip("_") for w in re.split(r"[._]", words[0]) if w.strip("_")]
    return any(w in FIRST_NAMES for w in words)


def cover_face_verdict(username: str) -> tuple:
    """Playwright cover-based face verification via tt_covers.py.
    Returns (verdict, captions): verdict is 'pass' | 'reject:faceless' | 'retry'
    (throttled/unverifiable). Uses the venv python (has playwright + opencv)."""
    try:
        proc = subprocess.run(
            [VENV_PY, os.path.join(HERE, "tt_covers.py"), "--json", username],
            capture_output=True, text=True, timeout=150)
        for line in proc.stdout.strip().splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            v = d.get("verdict")
            if v == "face_content":
                return "pass", d.get("captions") or []
            if v == "no_face_content":
                return "reject:faceless", []
            return "retry", []  # no_covers_found / error -> throttle or wall
        return "retry", []
    except Exception:
        return "retry", []


def has_face_or_person(info: dict) -> bool:
    """DEPRECATED avatar heuristic — kept only for reference. The authoritative
    face gate is cover_face_verdict (video-content face detection). Avatar
    checks proved unreliable in calibration (signals pages use real-photo
    avatars; only ~19% precision)."""
    return has_face_avatar(info.get("avatar") or "")


def check_lang_and_topic(bio: str) -> str:
    low = bio.lower()
    if any(f in low for f in FUTURES):
        return "reject:futures_trader"
    if not any(k in low for k in BIO_KEYS):
        return "reject:not_forex"
    if any(w in low for w in OTHER_LANG):
        return "reject:other_language"
    if any(w in low for w in STOCK_KEYS):
        return "reject:not_forex"  # stocks/indices-only accounts excluded
    if any(w in low for w in CRYPTO_KEYS):
        return "reject:not_forex"  # crypto-only accounts excluded
    return "ok"


def caption_forex_check(captions: list) -> str:
    """Content-level market check on video captions.
    Returns 'ok' | 'reject:stocks' | 'reject:crypto' | 'reject:other_language' | 'no_evidence'."""
    if not captions:
        return "no_evidence"
    blob = " ".join(c.lower() for c in captions)
    if any(w in blob for w in OTHER_LANG):
        return "reject:other_language"
    if any(w in blob for w in STOCK_KEYS):
        return "reject:stocks"
    if any(w in blob for w in CRYPTO_KEYS):
        return "reject:crypto"
    if any(w in blob for w in FX_KEYS):
        return "ok"  # explicit forex signal in content
    return "no_evidence"


# ------------------------------------------------------------ delivery --
def fmt_f(n: int) -> str:
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def send_batch(leads: list) -> None:
    lines = []
    for u, i in leads:
        url = f"instagram.com/{u}" if i.get("platform") == "instagram" else f"tiktok.com/@{u}"
        line = f"@{u} — {fmt_f(i['followers'])} — {url}"
        if i.get("email"):
            line += f" — {i['email']}"
        if i.get("eng_rate"):
            line += f" (eng {i['eng_rate']}%)"
        lines.append(line)
    msg = "📊 WINNER LEADS ({}):\n".format(len(lines)) + "\n".join(lines)
    subprocess.run(["imsg", "send", "--to", PHONE, "--text", msg], timeout=60)
    print(msg)


# ----------------------------------------------------------------- main --
def main() -> None:
    st = load_state()
    pending = [u for u in st.get("pending", []) if u not in st["sent"]]

    # --- HUNT: rotate queries ---
    qidx = st.get("qidx", 0)
    queries = []
    for _ in range(3):
        kw = KEYWORDS[qidx % len(KEYWORDS)]
        qidx += 1
        region = REGIONS[qidx % len(REGIONS)]
        queries.append(f'site:instagram.com "{kw}" {region}')
        queries.append(f'site:tiktok.com "{kw}" {region}')
    st["qidx"] = qidx
    for q in queries:
        html = ddg(q)
        new_h = extract_handles(html)
        for h in new_h:
            if h not in st["sent"] and h not in st["rejected"] and h not in pending:
                pending.append(h)
        time.sleep(4)

    # --- VERIFY up to VERIFY_PER_TICK per run (politely spaced) ---
    newly = []
    still = []
    cover_budget = [COVER_CHECKS_PER_TICK]
    for u in pending[:VERIFY_PER_TICK]:
        if u in st["sent"]:
            continue
        verdict, info = verify_account(u, cover_budget)
        if verdict in ("fetch_failed", "retry") or info is None:
            still.append(u)
        elif verdict == "pass":
            if u not in st["sent"]:
                newly.append((u, info))
        else:
            st["rejected"][u] = verdict
        time.sleep(4)
    st["pending"] = [u for u in pending[VERIFY_PER_TICK:]] + [u for u in still if u not in st["sent"]]

    if newly:
        # only text when a full batch (or more) has accumulated; hold partial
        # batches in "ready" so we never spam 1-6 lead texts
        ready = list(st.get("ready", [])) + newly
        full, remainder = ready[: len(ready) // BATCH * BATCH], ready[len(ready) // BATCH * BATCH:]
        for i in range(0, len(full), BATCH):
            batch = full[i:i + BATCH]
            send_batch(batch)
            # mark sent ONLY after the text actually went out
            for u, _ in batch:
                if u not in st["sent"]:
                    st["sent"].append(u)
        st["ready"] = remainder
    save_state(st)


if __name__ == "__main__":
    main()
