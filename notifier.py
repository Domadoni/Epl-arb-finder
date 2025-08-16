"""
ENG Arb Notifier — betslip tuning
Adds env controls:
- CURRENCY (default "£")
- STAKE_ROUND (default "0.05")
- SHOW_EQUALIZED_PAYOUT (default "true")
- BANKROLL (default "100")
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

def is_target_book(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in TARGET_BOOK_KEYWORDS)

def implied_prob(odds: float, commission: float = 0.0) -> float:
    eff = odds * (1 - commission)
    return 1.0/eff if eff>0 else 1e9

def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params={"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "oddsFormat":"decimal"}, timeout=20)
    r.raise_for_status()
    return r.json()

def best_triplet_from_event(ev: dict):
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
    if not all(x in name_map for x in ["Home","Draw","Away"]): return None, []
    return f"{home} vs {away}", [("Home",*name_map["Home"]),("Draw",*name_map["Draw"]),("Away",*name_map["Away"])]

def round_stake(value: float, step: float) -> float:
    if step <= 0: return round(value, 2)
    return round(round(value / step) * step + 1e-9, 2)

def format_money(x: float, symbol: str) -> str:
    return f"{symbol}{x:,.2f}"

def compute_arbs(events: List[dict], min_roi_pct: float, commission_map: Dict[str, float]) -> List[dict]:
    out = []
    for ev in events:
        match, triplet = best_triplet_from_event(ev)
        if not triplet: continue
        if not any(is_target_book(b) for (_,_,b) in triplet): continue
        implieds = [implied_prob(o, commission_map.get(b,0.0)) for (_,o,b) in triplet]
        margin = 1.0 - sum(implieds)
        roi = max(margin*100.0, 0.0)
        if roi >= min_roi_pct:
            out.append({"match": match, "triplet": triplet, "roi_pct": round(roi,3)})
    return out

def stake_plan(triplet, bankroll, commission_map, round_step):
    implieds = [implied_prob(o, commission_map.get(b,0.0)) for (_,o,b) in triplet]
    tot = sum(implieds) or 1.0
    plan, payouts = [], []
    for (label, odds, book), ip in zip(triplet, implieds):
        stake = bankroll * (ip / tot)
        stake = round_stake(stake, round_step)
        payout = stake * odds * (1 - commission_map.get(book,0.0))
        payouts.append(payout)
        plan.append((label, book, odds, stake))
    eq = min(payouts) if payouts else 0.0
    return plan, eq

def build_betslip_text(league, match, roi_pct, bankroll, plan, currency_symbol, show_equalized, equalized_payout):
    lines = [f"Betslip — {league}", f"{match}", f"Bankroll: {format_money(bankroll, currency_symbol)}  |  ROI≈ {roi_pct:.2f}%", "-"*44]
    for label, book, odds, stake in plan:
        lines.append(f"{label:<5} @ {book[:18]:<18}  {odds:<5}  {format_money(stake, currency_symbol)}")
    if show_equalized:
        lines.append("-"*44)
        lines.append(f"Equalized payout (approx): {format_money(equalized_payout, currency_symbol)}")
    return "\n".join(lines)

def telegram_send(token: str, chat_id: str, text: str):
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": text, "parse_mode":"HTML","disable_web_page_preview":True},
                  timeout=20).raise_for_status()

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
    min_roi = float(os.environ.get("MIN_ROI_PCT","0.2"))
    regions = [x.strip() for x in os.environ.get("REGIONS","uk,eu").split(",") if x.strip()]

    all_arbs = []
    for (label, sport_key) in SPORTS:
        try:
            events = fetch_odds(api_key, sport_key, regions, ["h2h"])
        except Exception as e:
            print(f"Fetch failed for {label}: {e}", file=sys.stderr)
            continue
        for a in compute_arbs(events, min_roi, commission_map={}):
            a["league"] = label
            all_arbs.append(a)

    if not all_arbs:
        print("No arbs this run."); return

    digest = hashlib.sha256(json.dumps(all_arbs, sort_keys=True).encode("utf-8")).hexdigest()
    state_file = ".arb_state_hash"; prev = open(state_file).read().strip() if os.path.exists(state_file) else None
    if digest == prev: print("Arbs unchanged; not sending."); return
    with open(state_file,"w") as f: f.write(digest)

    # Build message; add betslips for ROI>5%
    lines = ["<b>New ENG arbs found</b> (incl. Paddy/Betfair/Sky):"]
    betslip_blocks = []
    count = 0
    for league,_ in SPORTS:
        chunk = [a for a in all_arbs if a["league"] == league]
        if not chunk: continue
        lines.append(f"\n<b>{league}</b>")
        for a in chunk[:5]:
            lines.append(f"• {a['match']} — ROI ~ {a['roi_pct']}%")
            lines.append(f"  H: {a['triplet'][0][1]} @ {a['triplet'][0][2]}")
            lines.append(f"  D: {a['triplet'][1][1]} @ {a['triplet'][1][2]}")
            lines.append(f"  A: {a['triplet'][2][1]} @ {a['triplet'][2][2]}")
            count += 1
            if a["roi_pct"] > 5.0 and len(betslip_blocks) < 3:
                plan, equalized = stake_plan(a["triplet"], bankroll, commission_map={}, round_step=round_step)
                betslip_text = build_betslip_text(league, a["match"], a["roi_pct"], bankroll, plan, currency, show_eq, equalized)
                betslip_blocks.append(f"<pre>{betslip_text}</pre>")
        if count >= 12: break
    if betslip_blocks:
        lines.append("\n<b>High-ROI betslips (ROI>5%)</b>")
        lines.extend(betslip_blocks)

    telegram_send(token, chat_id, "\n".join(lines))
    print(f"Sent {len(all_arbs)} arbs.")

if __name__ == "__main__":
    main()
