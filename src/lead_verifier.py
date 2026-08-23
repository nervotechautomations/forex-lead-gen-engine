#!/usr/bin/env python3
"""IG lead verifier — retries pending Forex lead accounts against IG public API,
applies filters (758<=followers<20000, last post <=90d, eng rate >=1%, Spanish/forex),
texts newly qualified leads to the number in LEAD_PHONE via imsg. Silent when nothing new."""
import json, os, subprocess, time, datetime, urllib.request

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
STATE = os.path.expanduser('~/.hermes/scripts/ig_leads_state.json')
PHONE = os.environ.get('LEAD_PHONE')  # required at send time; never hardcode a real number
MIN_F, MAX_F, MAX_AGE_DAYS, MIN_ENG = 758, 100000, 90, 1.0
KEYWORDS = ['forex','trading','trader','fondeo','fondead','señal','senal','divisas','inversion','inversión','pip','broker','mercado']
EXCLUDE = ['futures','futuros','futuro trader','micro e-mini','e-mini','es futures','nq futures','topstep','apex trader','ninjatrader','tradovate','my funded futures','myfundedfutures']

def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    # Seed lists live in the local state file, never in source. This repo is
    # public; committing target usernames would publish both who is being
    # approached and who has already been contacted.
    return {"pending": [], "sent": [], "rejected": {}}

def fetch(u):
    req = urllib.request.Request(
        f'https://i.instagram.com/api/v1/users/web_profile_info/?username={u}',
        headers={'User-Agent': UA, 'x-ig-app-id': '936619743392459'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None

def evaluate(d):
    """Return (verdict, info). verdict: 'pass'|'reject:<reason>'"""
    u = d['data']['user']
    if u is None: return 'reject:unavailable', {}
    f = u['edge_followed_by']['count']
    bio = (u.get('biography') or '') + ' ' + (u.get('full_name') or '')
    info = {'followers': f, 'bio': u.get('biography',''), 'url': u.get('external_url'),
            'email': u.get('business_email'), 'private': u.get('is_private')}
    if u.get('is_private'): return 'reject:private', info
    if not (MIN_F <= f < MAX_F): return f'reject:followers={f}', info
    bio_lower = bio.lower()
    if not any(k in bio_lower for k in KEYWORDS): return 'reject:not_forex', info
    if any(k in bio_lower for k in EXCLUDE): return 'reject:futures_trader', info
    edges = u['edge_owner_to_timeline_media'].get('edges', [])
    if not edges: return 'reject:no_posts', info
    last_ts = max(e['node']['taken_at_timestamp'] for e in edges)
    age = (time.time() - last_ts) / 86400
    info['last_post'] = datetime.datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d')
    if age > MAX_AGE_DAYS: return f'reject:stale_{int(age)}d', info
    eng = sum(e['node']['edge_liked_by']['count'] + e['node']['edge_media_to_comment']['count']
              for e in edges) / len(edges)
    rate = 100 * eng / max(f, 1)
    info['eng_rate'] = round(rate, 2)
    if rate < MIN_ENG: return f'reject:low_eng_{rate:.2f}%', info
    return 'pass', info

def fmt_k(n):
    return f"{n/1000:.1f}k".replace('.0k','k') if n >= 1000 else str(n)

def main():
    st = load_state()
    newly, still = [], []
    for u in st['pending']:
        d = fetch(u)
        time.sleep(3)
        if not d or 'data' not in d or not d.get('data', {}).get('user'):
            still.append(u)  # rate-limited or error; retry next tick
            continue
        verdict, info = evaluate(d)
        if verdict == 'pass':
            if u not in st['sent']:
                newly.append((u, info))
                st['sent'].append(u)
        else:
            st['rejected'][u] = verdict
    st['pending'] = still
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, 'w'), indent=1)
    if newly:
        lines = [f"@{u} — {fmt_k(i['followers'])} — instagram.com/{u}" +
                 (f" — {i['email']}" if i.get('email') else '') +
                 f" (eng {i.get('eng_rate','?')}%, last {i.get('last_post','?')})"
                 for u, i in newly]
        msg = "📊 New verified Forex leads:\n" + "\n".join(lines)
        subprocess.run(['imsg', 'send', '--to', PHONE, '--text', msg], timeout=60)
        print(msg)
    # empty stdout when nothing new -> silent tick

if __name__ == '__main__':
    main()
