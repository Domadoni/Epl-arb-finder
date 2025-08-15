"""
Arbitrage Suite — Streamlit UI (EPL + Championship + League One + League Two) with Telegram alerts
"""
import math, time, hashlib, json
from typing import Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st
from dateutil import parser as dtparser

BASE_URL = "https://api.the-odds-api.com/v4"

SPORT_KEYS = {
    "English Premier League (EPL)": "soccer_epl",
    "EFL Championship": "soccer_efl_championship",
    "EFL League One": "soccer_england_league1",
    "EFL League Two": "soccer_england_league2",
    "FA Cup": "soccer_fa_cup",
}

DEFAULT_REGIONS = ["uk", "eu"]
SUPPORTED_MARKETS = {"Match Result (1X2)": "h2h"}

TARGET_BOOK_KEYWORDS = {"paddy power", "paddypower", "betfair", "sky bet", "skybet"}
def is_target_book(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in TARGET_BOOK_KEYWORDS)

def telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=15).raise_for_status()
    except Exception as e:
        st.warning(f"Telegram send failed: {e}")

def hash_arbs_summary(arbs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(arbs, sort_keys=True).encode("utf-8")).hexdigest()

def implied_prob(decimal_odds: float, commission: float = 0.0) -> float:
    if decimal_odds <= 1e-9:
        return float("inf")
    effective_odds = decimal_odds * (1 - commission)
    if effective_odds <= 1e-9:
        return float("inf")
    return 1.0 / effective_odds

def stake_split_for_arbitrage(best_odds: List[Tuple[str, float, str]], bankroll: float, commission_map: Dict[str, float]):
    rows = []
    implieds = []
    for outcome, odds, book in best_odds:
        c = commission_map.get(book, 0.0)
        ip = 1.0 / (odds * (1 - c)) if odds > 0 else float("inf")
        implieds.append(ip)
    total_ip = sum(implieds)
    margin = 1.0 - total_ip
    payouts = []
    for (outcome, odds, book), ip in zip(best_odds, implieds):
        stake = bankroll * (ip / total_ip) if total_ip > 0 else 0.0
        c = commission_map.get(book, 0.0)
        payout = stake * odds * (1 - c)
        payouts.append(payout)
        rows.append({"Outcome": outcome, "Bookmaker": book, "Odds": round(odds,3), "Commission": f"{int(c*100)}%", "Stake": round(stake,2), "Net Payout if Wins": round(payout,2)})
    min_payout = min(payouts) if payouts else 0.0
    roi_pct = ((min_payout - bankroll) / bankroll * 100.0) if bankroll else 0.0
    import pandas as pd
    return pd.DataFrame(rows), roi_pct, margin

@st.cache_data(ttl=60)
def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    params = {"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "oddsFormat": "decimal"}
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"API error {r.status_code}: {r.text}")
    return r.json()

st.set_page_config(page_title="Arb Finder (ENG tiers)", page_icon="⚽", layout="wide")
st.title("⚽ English Football Arbitrage Finder (1X2)")

# Auto-refresh every 30 minutes while page open
if "last_tick" not in st.session_state:
    st.session_state["last_tick"] = time.time()
elif time.time() - st.session_state["last_tick"] > 30*60:
    st.session_state["last_tick"] = time.time()
    st.experimental_rerun()

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("The Odds API key", type="password")
    sport_label = st.selectbox("Competition", list(SPORT_KEYS.keys()), index=0)
    regions = st.multiselect("Regions (bookmaker regions)", ["uk","eu","us","au"], default=DEFAULT_REGIONS)
    market_label = st.selectbox("Market", list(SUPPORTED_MARKETS.keys()), index=0)
    bankroll = st.number_input("Bankroll to allocate per bet (£)", min_value=0.0, value=100.0, step=10.0)
    min_roi = st.slider("Minimum ROI to show (percent)", min_value=-10.0, max_value=10.0, value=0.2, step=0.1)
    include_commission = st.checkbox("Include per‑book commission (optional)", value=False)
    filter_to_target = st.checkbox("Only show arbs incl. Paddy/Betfair/Sky", value=True)

    commission_map: Dict[str, float] = {}
    if include_commission:
        st.caption("Set commission per bookmaker/exchange (0–10%). Leave blank for 0%.")

    st.divider()
    st.caption("Odds move quickly. Use the refresh button below before acting.")
    refresh = st.button("🔄 Refresh odds")

    st.subheader("🔔 Telegram alerts (optional)")
    tg_bot_token_default = st.secrets.get("telegram", {}).get("bot_token", "") if "telegram" in st.secrets else ""
    tg_chat_id_default = st.secrets.get("telegram", {}).get("chat_id", "") if "telegram" in st.secrets else ""
    bot_token = st.text_input("Bot token", value=tg_bot_token_default, type="password", help="Create via @BotFather")
    chat_id = st.text_input("Chat ID", value=tg_chat_id_default, help="Your user or group chat id")
    cA, cB = st.columns(2)
    with cA:
        test_clicked = st.button("Send test")
    with cB:
        notify_live = st.checkbox("Notify when new arbs appear", value=False)
    if test_clicked:
        telegram_send(bot_token, chat_id, "✅ Test from ENG Arb Finder — your Telegram is wired up.")
        st.success("Test sent (check Telegram).")

sport_key = SPORT_KEYS[sport_label]; market_key = SUPPORTED_MARKETS[market_label]

if not api_key:
    st.info("Enter your API key in the sidebar to fetch live odds."); st.stop()

try:
    events = fetch_odds(api_key, sport_key, regions, [market_key])
except Exception as e:
    st.error(f"Failed to fetch odds: {e}"); st.stop()

if include_commission and events:
    all_books = sorted({b.get("title", b.get("key","")) for ev in events for b in ev.get("bookmakers",[]) })
    with st.sidebar:
        for bk in all_books:
            key = f"commission_{bk}"
            pct = st.number_input(f"{bk}", min_value=0.0, max_value=0.10, value=0.0, step=0.005, key=key)
            commission_map[bk] = pct

records = []
for ev in events:
    home = ev.get("home_team"); away = ev.get("away_team")
    commence_time = dtparser.parse(ev.get("commence_time")) if ev.get("commence_time") else None

    best = {}
    for bk in ev.get("bookmakers", []):
        book_name = bk.get("title") or bk.get("key")
        for market in bk.get("markets", []):
            if market.get("key") != market_key: continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name"); price = float(outcome.get("price"))
                if name not in best or price > best[name][0]: best[name] = (price, book_name)

    if market_key == "h2h":
        needed = [home, "Draw", away]; name_map = {}
        for k in list(best.keys()):
            low = k.lower()
            if "draw" in low: name_map["Draw"] = best[k]
            elif home and home.lower() in low: name_map[home] = best[k]
            elif away and away.lower() in low: name_map[away] = best[k]
        if not all(x in name_map for x in needed): continue
        best_triplet = [("Home", name_map[home][0], name_map[home][1]), ("Draw", name_map["Draw"][0], name_map["Draw"][1]), ("Away", name_map[away][0], name_map[away][1])]
    else:
        continue

    if filter_to_target:
        books_in_arb = {b for (_,_,b) in best_triplet}
        if not any(is_target_book(b) for b in books_in_arb): continue

    implieds = [1.0/(o*(1-commission_map.get(b,0.0))) for (_,o,b) in best_triplet]
    margin = 1.0 - sum(implieds)
    roi_est = max(margin*100.0, 0.0)

    if roi_est >= min_roi:
        plan_df, roi_pct, margin2 = stake_split_for_arbitrage(best_triplet, bankroll, commission_map)
        records.append({"Match": f"{home} vs {away}", "Kickoff": commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else "", "Best Home": f"{best_triplet[0][1]} @ {best_triplet[0][2]}", "Best Draw": f"{best_triplet[1][1]} @ {best_triplet[1][2]}", "Best Away": f"{best_triplet[2][1]} @ {best_triplet[2][2]}", "Arb Margin %": round(margin2*100,3), "Plan": plan_df})

st.subheader("Results")
if not records:
    msg = "No surebets found at the current thresholds."
    if filter_to_target: msg += " (Filtered to Paddy/Betfair/Sky.)"
    st.warning(msg + " Try lowering the ROI filter or refreshing.")
else:
    for rec in records:
        with st.expander(f"{rec['Match']} — Kickoff {rec['Kickoff']} — Margin {rec['Arb Margin %']}%"):
            c1,c2,c3 = st.columns(3)
            with c1: st.metric("Best Home", rec["Best Home"].split(" @ ")[0], help=rec["Best Home"].split(" @ ")[1])
            with c2: st.metric("Best Draw", rec["Best Draw"].split(" @ ")[0], help=rec["Best Draw"].split(" @ ")[1])
            with c3: st.metric("Best Away", rec["Best Away"].split(" @ ")[0], help=rec["Best Away"].split(" @ ")[1])
            st.dataframe(rec["Plan"], use_container_width=True)

if records:
    flat = [{"Match": r["Match"], "Kickoff": r["Kickoff"], "Best Home": r["Best Home"], "Best Draw": r["Best Draw"], "Best Away": r["Best Away"], "Arb Margin %": r["Arb Margin %"]} for r in records]
    csv = pd.DataFrame(flat).to_csv(index=False).encode("utf-8")
    st.download_button("Download summary CSV", data=csv, file_name="surebets_summary.csv", mime="text/csv")

arb_summaries = [{"match": r["Match"], "best_home": r["Best Home"], "best_draw": r["Best Draw"], "best_away": r["Best Away"], "margin_pct": r["Arb Margin %"]} for r in records]
curr_digest = hashlib.sha256(json.dumps(arb_summaries, sort_keys=True).encode("utf-8")).hexdigest()
prev_digest = st.session_state.get("last_arb_digest")
if 'notify_live' in locals() and notify_live and arb_summaries and curr_digest != prev_digest:
    lines = ["<b>New arbs found</b>:" + (" (incl. Paddy/Betfair/Sky)" if filter_to_target else "")]
    for a in arb_summaries[:10]:
        lines.append(f"• {a['match']} — Margin ~ {a['margin_pct']}%\n  H: {a['best_home']}\n  D: {a['best_draw']}\n  A: {a['best_away']}")
    telegram_send(bot_token, chat_id, "\n".join(lines))
    st.toast("Sent Telegram alert for new arbs ✅", icon="✅")
st.session_state["last_arb_digest"] = curr_digest
