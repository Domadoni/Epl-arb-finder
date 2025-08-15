"""
Arb Notifier with Test Mode — run manually to send a test message via Telegram.
"""

import os, sys, json, hashlib
from typing import Dict, List, Tuple
import requests
from dateutil import parser as dtparser

BASE_URL = "https://api.the-odds-api.com/v4"

TARGET_BOOK_KEYWORDS = {"paddy power", "paddypower", "betfair", "sky bet", "skybet"}

def is_target_book(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in TARGET_BOOK_KEYWORDS)

def implied_prob(odds: float, commission: float = 0.0) -> float:
    eff = odds * (1 - commission)
    if eff <= 0: 
        return 1e9
    return 1.0 / eff

def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    params = {
        "apiKey": api_key,
        "regions": ",".join(regions),
        "markets": ",".join(markets),
        "oddsFormat": "decimal",
    }
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def compute_arbs(events: List[dict], min_roi_pct: float, commission_map: Dict[str, float]) -> List[dict]:
    found = []
    for ev in events:
        home = ev.get("home_team")
        away = ev.get("away_team")
        best = {}
        for bk in ev.get("bookmakers", []):
            book_name = bk.get("title") or bk.get("key")
            for market in bk.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = float(outcome.get("price"))
                    if name not in best or price > best[name][0]:
                        best[name] = (price, book_name)
        name_map = {}
        for k, v in list(best.items()):
            low = k.lower()
            if "draw" in low:
                name_map["Draw"] = v
            elif home and home.lower() in low:
                name_map["Home"] = v
            elif away and away.lower() in low:
                name_map["Away"] = v
        if not all(x in name_map for x in ["Home", "Draw", "Away"]):
            continue

        triplet = [("Home", *name_map["Home"]), ("Draw", *name_map["Draw"]), ("Away", *name_map["Away"])]
        if not any(is_target_book(b) for (_, _, b) in triplet):
            continue

        implieds = [implied_prob(o, commission_map.get(b, 0.0)) for (_, o, b) in triplet]
        margin = 1.0 - sum(implieds)
        roi_pct = max(margin * 100.0, 0.0)
        if roi_pct >= min_roi_pct:
            found.append({
                "match": f"{home} vs {away}",
                "best_home": f"{triplet[0][1]} @ {triplet[0][2]}",
                "best_draw": f"{triplet[1][1]} @ {triplet[1][2]}",
                "best_away": f"{triplet[2][1]} @ {triplet[2][2]}",
                "roi_pct": round(roi_pct, 3),
            })
    return found

def telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()

def main():
    api_key = os.environ.get("ODDS_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    min_roi = float(os.environ.get("MIN_ROI_PCT", "0.2"))
    regions = [x.strip() for x in os.environ.get("REGIONS", "uk,eu").split(",") if x.strip()]
    test_mode = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")

    if not (bot_token and chat_id):
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID", file=sys.stderr)
        sys.exit(1)

    if test_mode:
        telegram_send(bot_token, chat_id, "✅ Test message from EPL Arb Notifier — your Telegram setup works!")
        print("Test message sent.")
        return

    if not api_key:
        print("Missing ODDS_API_KEY", file=sys.stderr)
        sys.exit(1)

    events = fetch_odds(api_key, "soccer_epl", regions, ["h2h"])
    commission_map: Dict[str, float] = {}
    arbs = compute_arbs(events, min_roi, commission_map)
    if not arbs:
        print("No arbs this run.")
        return

    digest = hashlib.sha256(json.dumps(arbs, sort_keys=True).encode("utf-8")).hexdigest()
    state_file = ".arb_state_hash"
    last = None
    if os.path.exists(state_file):
        last = open(state_file, "r").read().strip()
    if digest == last:
        print("Arbs unchanged; not sending notification.")
        return
    with open(state_file, "w") as f:
        f.write(digest)

    lines = ["<b>New EPL arbs found</b> (includes Paddy/Betfair/Sky):"]
    for a in arbs[:10]:
        lines.append(f"• {a['match']} — ROI ~ {a['roi_pct']}%\n  H: {a['best_home']}\n  D: {a['best_draw']}\n  A: {a['best_away']}")
    msg = "\n".join(lines)
    telegram_send(bot_token, chat_id, msg)
    print(f"Sent {len(arbs)} arbs.")

if __name__ == "__main__":
    main()
