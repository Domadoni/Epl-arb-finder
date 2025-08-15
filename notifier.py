"""
ENG Arb Notifier — minute-by-minute runner with smart gating
- Executes every minute BETWEEN RAPID_WINDOW_START_ISO and RAPID_WINDOW_END_ISO (in TIMEZONE)
- Executes only on 30‑minute marks OUTSIDE that window
- Scans EPL, Championship, League One, League Two, FA Cup, EFL Cup

Env (set in workflow or repository secrets/variables):
- ODDS_API_KEY (secret, required)
- TELEGRAM_BOT_TOKEN (secret, required)
- TELEGRAM_CHAT_ID (secret, required)
- MIN_ROI_PCT (var, optional; default 0.2)
- REGIONS (var, optional; default "uk,eu")
- TIMEZONE (var, optional; default "Europe/Dublin")
- RAPID_WINDOW_START_ISO (var, optional; ISO without TZ, e.g. "2025-08-16T12:00:00")
- RAPID_WINDOW_END_ISO   (var, optional; ISO without TZ, e.g. "2025-08-16T17:00:00")
- TEST_MODE (var, optional; "true" to send a test message immediately)
"""
import os, sys, json, hashlib, requests
from typing import Dict, List
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # py3.9+
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

def compute_arbs_for_events(events: List[dict], min_roi_pct: float, commission_map: Dict[str, float], league_label: str) -> List[dict]:
    out = []
    for ev in events:
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
        if not all(x in name_map for x in ["Home","Draw","Away"]): continue
        triplet = [("Home",*name_map["Home"]),("Draw",*name_map["Draw"]),("Away",*name_map["Away"])]
        if not any(is_target_book(b) for (_,_,b) in triplet): continue
        implieds = [implied_prob(o, commission_map.get(b,0.0)) for (_,o,b) in triplet]
        margin = 1.0 - sum(implieds)
        roi = max(margin*100.0, 0.0)
        if roi >= min_roi_pct:
            out.append({"league": league_label,
                        "match": f"{home} vs {away}",
                        "best_home": f"{triplet[0][1]} @ {triplet[0][2]}",
                        "best_draw": f"{triplet[1][1]} @ {triplet[1][2]}",
                        "best_away": f"{triplet[2][1]} @ {triplet[2][2]}",
                        "roi_pct": round(roi,3)})
    return out

def telegram_send(token: str, chat_id: str, text: str):
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": text, "parse_mode":"HTML","disable_web_page_preview":True},
                  timeout=20).raise_for_status()

def within_rapid_window(now_local, tzname: str, start_iso: str, end_iso: str) -> bool:
    """Return True if now_local (timezone-aware) falls within [start, end)."""
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
    """Minute-level gating:
       - inside rapid window: run every minute
       - outside: run only when minute % 30 == 0
    """
    tzname = os.environ.get("TIMEZONE", "Europe/Dublin")
    tz = ZoneInfo(tzname) if ZoneInfo else None
    now_local = datetime.now(tz) if tz else datetime.utcnow()
    start_iso = os.environ.get("RAPID_WINDOW_START_ISO", "")
    end_iso   = os.environ.get("RAPID_WINDOW_END_ISO", "")
    in_window = within_rapid_window(now_local, tzname, start_iso, end_iso)
    if in_window:
        return True
    # outside window: only run on 00 or 30 past the hour
    return now_local.minute % 30 == 0

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    test_mode = os.environ.get("TEST_MODE","").lower() in ("1","true","yes")
    if not (token and chat_id):
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr); sys.exit(1)
    if test_mode:
        telegram_send(token, chat_id, "✅ Test from ENG Arb Notifier — your Telegram is wired up."); print("Test sent."); return

    # Smart gating
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
        all_arbs.extend(compute_arbs_for_events(events, min_roi, commission_map={}, league_label=label))

    if not all_arbs:
        print("No arbs this run."); return

    digest = hashlib.sha256(json.dumps(all_arbs, sort_keys=True).encode("utf-8")).hexdigest()
    state_file = ".arb_state_hash"; prev = open(state_file).read().strip() if os.path.exists(state_file) else None
    if digest == prev: print("Arbs unchanged; not sending."); return
    with open(state_file,"w") as f: f.write(digest)

    lines = ["<b>New ENG arbs found</b> (incl. Paddy/Betfair/Sky):"]
    count = 0
    for league,_ in SPORTS:
        chunk = [a for a in all_arbs if a["league"] == league]
        if not chunk: continue
        lines.append(f"\n<b>{league}</b>")
        for a in chunk[:5]:
            lines.append(f"• {a['match']} — ROI ~ {a['roi_pct']}%\n  H: {a['best_home']}\n  D: {a['best_draw']}\n  A: {a['best_away']}")
            count += 1
            if count >= 12: break
        if count >= 12: break

    telegram_send(token, chat_id, "\n".join(lines))
    print(f"Sent {len(all_arbs)} arbs.")

if __name__ == "__main__":
    main()
