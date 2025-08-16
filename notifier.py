
"""
ENG Arb Notifier — 1X2 + Corners O/U
- Separate thresholds: MIN_ROI_PCT (scan), MIN_ROI_PCT_NOTIFY (notify)
- Allowed bookmakers filter (ALLOWED_BOOKMAKERS)
- Betfair+Partner filter (REQUIRE_BETFAIR_PAIR + PARTNER_BOOKS)
- Minutely schedule with in-script gating window
"""
import os, sys, json, hashlib, requests
from typing import Dict, List, Tuple
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

BASE_URL = "https://api.the-odds-api.com/v4"
SPORTS = [
    ("EPL", "soccer_epl"),
    ("Championship", "soccer_efl_championship"),
    ("League One", "soccer_england_league1"),
    ("League Two", "soccer_england_league2"),
    ("FA Cup", "soccer_fa_cup"),
    ("EFL Cup", "soccer_efl_cup"),
]

TARGET_BOOK_KEYWORDS = {"paddy power","paddypower","betfair","sky bet","skybet"}

# Allowed list normalization
DEFAULT_ALLOWED_BOOKS = ["Bet365","Ladbrokes","William Hill","Pinnacle","Unibet","Coral"]
def norm(name: str) -> str:
    n = (name or '').strip().lower()
    n = n.replace('ladbrook', 'ladbroke').replace('ladbrooks', 'ladbrokes')
    n = n.replace('uni bet', 'unibet')
    n = n.replace('will hill','william hill')
    n = n.replace('boyle sports','boylesports').replace('boyle-sports','boylesports')
    return n
ALLOWED_BOOKS_CANON = {
    'bet365': {'bet365'},
    'ladbrokes': {'ladbroke','ladbrokes'},
    'william hill': {'william hill','williamhill','will hill'},
    'pinnacle': {'pinnacle','pinny'},
    'unibet': {'unibet','uni bet'},
    'coral': {'coral'},
}
def parse_allowed_env() -> set:
    raw = os.environ.get('ALLOWED_BOOKMAKERS','').strip()
    if not raw:
        return {norm(x) for x in DEFAULT_ALLOWED_BOOKS}
    return {norm(x) for x in raw.split(',') if x.strip()}
def is_allowed(name: str, allowed_norm: set) -> bool:
    ln = norm(name)
    if ln in allowed_norm:
        return True
    for canon, variants in ALLOWED_BOOKS_CANON.items():
        if ln in variants and canon in allowed_norm:
            return True
    return False

# Betfair+Partner
BETFAIR_KEYS = {"betfair","betfair exchange"}
DEFAULT_PARTNERS = {"bet365","ladbrokes","william hill","boylesports","boyle sports","coral"}
def parse_partner_env() -> set:
    raw = os.environ.get('PARTNER_BOOKS','').strip()
    if not raw:
        return DEFAULT_PARTNERS
    return {x.strip().lower() for x in raw.split(',') if x.strip()}
def is_betfair_exchange(name: str) -> bool:
    ln = norm(name)
    return any(k in ln for k in BETFAIR_KEYS)
def is_partner_book(name: str, partners: set) -> bool:
    ln = norm(name)
    return any(p in ln for p in partners)

def is_target_book(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in TARGET_BOOK_KEYWORDS)

def implied_prob(odds: float, commission: float = 0.0) -> float:
    eff = odds * (1 - commission)
    return 1.0/eff if eff>0 else 1e9

def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params={"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "oddsFormat":"decimal"}, timeout=25)
    r.raise_for_status()
    return r.json()

def extract_h2h(ev: dict) -> Tuple[str, List[Tuple[str,float,str]]]:
    home, away = ev.get("home_team"), ev.get("away_team")
    best = {}
    for bk in ev.get("bookmakers", []):
        book_name = bk.get("title") or bk.get("key")
        for m in bk.get("markets", []):
            if m.get("key") != "h2h": continue
            for o in m.get("outcomes", []):
                name, price = o.get("name"), float(o.get("price"))
                if name not in best or price > best[name][0]: best[name] = (price, book_name)
    name_map = {}
    for k,v in best.items():
        low = k.lower()
        if "draw" in low: name_map["Draw"] = v
        elif home and home.lower() in low: name_map["Home"] = v
        elif away and away.lower() in low: name_map["Away"] = v
    if not all(x in name_map for x in ["Home","Draw","Away"]): 
        return None, []
    return f"{home} vs {away}", [("Home",*name_map["Home"]),("Draw",*name_map["Draw"]),("Away",*name_map["Away"])]

def extract_corners_ou(ev: dict) -> Tuple[str, List[Tuple[str,float,str]]]:
    home, away = ev.get("home_team"), ev.get("away_team")
    match_str = f"{home} vs {away}"
    best_ou = {}
    line_seen = None
    for bk in ev.get("bookmakers", []):
        book_name = bk.get("title") or bk.get("key")
        for m in bk.get("markets", []):
            mkey = m.get("key","")
            if mkey not in ("totals","totals_corners","corners","total_corners","corners_totals"):
                continue
            blob = " ".join([str(m.get("key","")), str(m.get("outcomes","")), str(bk.get("title",""))]).lower()
            if "corner" not in blob:
                continue
            for o in m.get("outcomes", []):
                name = (o.get("name") or "").strip()
                if name.lower() not in ("over","under"):
                    continue
                price = float(o.get("price"))
                point = o.get("point")
                label = f"{name.title()} {point}" if point is not None else name.title()
                if point is not None:
                    line_seen = point
                if label not in best_ou or price > best_ou[label][0]:
                    best_ou[label] = (price, book_name)
    if not best_ou:
        return None, []
    over_key = f"Over {line_seen}" if line_seen is not None else "Over"
    under_key = f"Under {line_seen}" if line_seen is not None else "Under"
    if over_key not in best_ou or under_key not in best_ou:
        overs = [k for k in best_ou if k.lower().startswith("over")]
        unders = [k for k in best_ou if k.lower().startswith("under")]
        if not (overs and unders):
            return None, []
        over_key, under_key = overs[0], unders[0]
    return match_str, [(over_key, best_ou[over_key][0], best_ou[over_key][1]), (under_key, best_ou[under_key][0], best_ou[under_key][1])]

def compute_arbs_for_outcomes(outcomes: List[Tuple[str,float,str]], commission_map: Dict[str,float]) -> Tuple[float, float]:
    implieds = [implied_prob(o, commission_map.get(b,0.0)) for (_,o,b) in outcomes]
    margin = 1.0 - sum(implieds)
    roi = max(margin*100.0, 0.0)
    return roi, margin

def stake_plan(outcomes: List[Tuple[str,float,str]], bankroll: float, commission_map: Dict[str,float], round_step: float) -> Tuple[List[Tuple[str,str,float,float]], float]:
    implieds = [implied_prob(o, commission_map.get(b,0.0)) for (_,o,b) in outcomes]
    tot = sum(implieds) or 1.0
    plan, payouts = [], []
    for (label, odds, book), ip in zip(outcomes, implieds):
        stake = bankroll * (ip / tot)
        payout = stake * odds * (1 - commission_map.get(book,0.0))
        payouts.append(payout)
        plan.append((label, book, odds, round(stake,2)))
    eq = min(payouts) if payouts else 0.0
    return plan, eq

def telegram_send(token: str, chat_id: str, text: str):
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": text, "parse_mode":"HTML","disable_web_page_preview":True},
                  timeout=25).raise_for_status()

def within_rapid_window(now_local, tzname: str, start_iso: str, end_iso: str) -> bool:
    if not (start_iso and end_iso and tzname and ZoneInfo):
        return False
    tz = ZoneInfo(tzname)
    try:
        start = datetime.fromisoformat(start_iso).replace(tzinfo=tz)
        end = datetime.fromisoformat(end_iso).replace(tzinfo=tz)
    except Exception:
        return False
    return start <= now_local < end

def should_execute_now() -> bool:
    tzname = os.environ.get("TIMEZONE", "Europe/Dublin")
    tz = ZoneInfo(tzname) if ZoneInfo else None
    now_local = datetime.now(tz) if tz else datetime.utcnow()
    start_iso = os.environ.get("RAPID_WINDOW_START_ISO", "")
    end_iso   = os.environ.get("RAPID_WINDOW_END_ISO", "")
    in_window = within_rapid_window(now_local, tzname, start_iso, end_iso)
    if in_window:
        return True
    return now_local.minute % 30 == 0

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    bankroll = float(os.environ.get("BANKROLL", "100"))
    currency = os.environ.get("CURRENCY", "£")
    round_step = float(os.environ.get("STAKE_ROUND", "0.05"))
    show_eq = os.environ.get("SHOW_EQUALIZED_PAYOUT", "true").lower() in ("1","true","yes")
    include_corners = os.environ.get("INCLUDE_CORNERS", "true").lower() in ("1","true","yes")
    require_betfair_pair = os.environ.get("REQUIRE_BETFAIR_PAIR", "false").lower() in ("1","true","yes")
    test_mode = os.environ.get("TEST_MODE","").lower() in ("1","true","yes")
    if not (token and chat_id):
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr); sys.exit(1)
    if test_mode:
        telegram_send(token, chat_id, "✅ Test from ENG Arb Notifier — your Telegram is wired up."); print("Test sent."); return

    if not should_execute_now():
        print("Skipping this minute per schedule gating."); return

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("Missing ODDS_API_KEY", file=sys.stderr); sys.exit(1)
    min_roi_scan = float(os.environ.get("MIN_ROI_PCT","0.2"))
    notify_env = os.environ.get("MIN_ROI_PCT_NOTIFY","").strip()
    try:
        min_roi_notify = float(notify_env) if notify_env != "" else min_roi_scan
    except Exception:
        min_roi_notify = min_roi_scan
    regions = [x.strip() for x in os.environ.get("REGIONS","uk,eu").split(",") if x.strip()]

    all_arbs = []
    for (league, sport_key) in SPORTS:
        try:
            events = fetch_odds(api_key, sport_key, regions, ["h2h","totals"])
        except Exception as e:
            print(f"Fetch failed for {league}: {e}", file=sys.stderr)
            continue

        # 1X2
        for ev in events:
            match, outcomes = extract_h2h(ev)
            if not outcomes: 
                continue
            if not any(is_target_book(b) for (_,_,b) in outcomes): 
                continue
            allowed_norm = parse_allowed_env()
            if not all(is_allowed(b, allowed_norm) for (_,_,b) in outcomes):
                continue
            roi, margin = compute_arbs_for_outcomes(outcomes, commission_map={})
            if roi >= min_roi_scan:
                all_arbs.append({"league":league, "market":"1X2", "match":match, "outcomes":outcomes, "roi_pct":round(roi,3)})

        # Corners O/U
        if include_corners:
            for ev in events:
                match, outcomes = extract_corners_ou(ev)
                if not outcomes:
                    continue
                if not any(is_target_book(b) for (_,_,b) in outcomes):
                    continue
                allowed_norm = parse_allowed_env()
                if not all(is_allowed(b, allowed_norm) for (_,_,b) in outcomes):
                    continue
                if require_betfair_pair and len(outcomes) == 2:
                    partners = parse_partner_env()
                    b1 = outcomes[0][2]; b2 = outcomes[1][2]
                    cond = (is_betfair_exchange(b1) and is_partner_book(b2, partners)) or (is_betfair_exchange(b2) and is_partner_book(b1, partners))
                    if not cond:
                        continue
                roi, margin = compute_arbs_for_outcomes(outcomes, commission_map={})
                if roi >= min_roi_scan:
                    all_arbs.append({"league":league, "market":"Corners O/U", "match":match, "outcomes":outcomes, "roi_pct":round(roi,3)})

    if not all_arbs:
        print("No arbs this run."); return

    # Prepare notified set
    notified_arbs = [a for a in all_arbs if a.get('roi_pct', 0) >= min_roi_notify]
    if not notified_arbs:
        print("No arbs meet notify threshold; not sending."); return

    digest = hashlib.sha256(json.dumps(notified_arbs, sort_keys=True).encode("utf-8")).hexdigest()
    state_file = ".arb_state_hash"; prev = open(state_file).read().strip() if os.path.exists(state_file) else None
    if digest == prev: 
        print("Arbs unchanged; not sending."); 
        return
    with open(state_file,"w") as f: f.write(digest)

    lines = ["<b>New ENG arbs found</b> (filters applied)"]
    betslip_blocks = []
    count = 0
    for league,_ in SPORTS:
        chunk = [a for a in notified_arbs if a["league"] == league]
        if not chunk: 
            continue
        lines.append(f"\n<b>{league}</b>")
        for a in chunk[:6]:
            oc = a["outcomes"]
            lines.append(f"• [{a['market']}] {a['match']} — ROI ~ {a['roi_pct']}%")
            for lbl, odds, book in oc:
                lines.append(f"  {lbl}: {odds} @ {book}")
            count += 1
            if count >= 12:
                break

    telegram_send(token, chat_id, "\n".join(lines))
    print(f"Sent {len(notified_arbs)} arbs.")

if __name__ == "__main__":
    main()
