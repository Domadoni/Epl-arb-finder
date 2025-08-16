"""
ENG Arbitrage — All competitions, with tunable betslip formatting
New controls:
- Currency symbol (e.g., £, €, $)
- Stake rounding step (e.g., 0.01, 0.05, 0.10)
- Odds decimal places (2–3 typical)
- Show equalized payout line toggle
"""
import math, time, hashlib, json, urllib.parse
from typing import Dict, List, Tuple
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

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
    "EFL Cup (Carabao Cup)": "soccer_efl_cup",
}

DEFAULT_REGIONS = ["uk", "eu"]
SUPPORTED_MARKETS = {
    "Match Result (1X2)": "h2h",
    "Corners Over/Under": "totals_corners"
}

TARGET_BOOK_KEYWORDS = {"paddy power", "paddypower", "betfair", "sky bet", "skybet"}
BOOKMAKER_BASELINKS = [
    ("paddy power", "https://www.paddypower.com/"),
    ("betfair", "https://www.betfair.com/exchange/plus/"),
    ("sky bet", "https://m.skybet.com/"),
    ("skybet", "https://m.skybet.com/"),
]

def is_target_book(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in TARGET_BOOK_KEYWORDS)

def bookmaker_link(book_name: str, match_str: str) -> str:
    name_l = (book_name or "").lower()
    for key, url in BOOKMAKER_BASELINKS:
        if key in name_l:
            return url
    q = urllib.parse.quote_plus(f"{book_name} {match_str}")
    return f"https://www.google.com/search?q={q}"

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
        rows.append({"Outcome": outcome, "Bookmaker": book, "Odds": round(odds,3), "Commission": f"{int(c*100)}%", "Stake": stake, "Net Payout if Wins": payout})
    min_payout = min(payouts) if payouts else 0.0
    roi_pct = ((min_payout - bankroll) / bankroll * 100.0) if bankroll else 0.0
    import pandas as pd
    return pd.DataFrame(rows), roi_pct, margin

def round_stake(value: float, step: float) -> float:
    if step <= 0: return round(value, 2)
    return round(round(value / step) * step + 1e-9, 2)

def format_money(x: float, symbol: str) -> str:
    return f"{symbol}{x:,.2f}"

def build_betslip_text(comp: str, match_str: str, kickoff: str, roi_pct: float, bankroll: float, plan_df: pd.DataFrame, currency_symbol: str, stake_step: float, odds_decimals: int, show_equalized: bool) -> str:
    # Round stakes for the shareable slip
    plan = plan_df.copy()
    plan["Stake"] = plan["Stake"].apply(lambda v: round_stake(float(v), stake_step))
    plan["Odds"] = plan["Odds"].apply(lambda v: round(float(v), odds_decimals))
    # Compute equalized payout after rounding
    if len(plan):
        net_payouts = plan.apply(lambda r: float(r["Stake"]) * float(r["Odds"]) * (1 - (0 if isinstance(r["Commission"], str) else float(r["Commission"]))), axis=1) if False else plan["Net Payout if Wins"]
        equalized = float(net_payouts.min()) if len(plan) else 0.0
    else:
        equalized = 0.0
    lines = [
        f"Betslip — {comp}",
        f"{match_str} (KO {kickoff})",
        f"Bankroll: {format_money(bankroll, currency_symbol)}  |  ROI≈ {roi_pct:.2f}%",
        "-"*44
    ]
    for _, row in plan.iterrows():
        lines.append(f"{row['Outcome']:<5} @ {row['Bookmaker'][:18]:<18}  {row['Odds']:<5}  {format_money(row['Stake'], currency_symbol)}")
    if show_equalized and len(plan):
        lines.append("-"*44)
        lines.append(f"Equalized payout (approx): {format_money(equalized, currency_symbol)}")
    return "\n".join(lines)

@st.cache_data(ttl=60)
def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    params = {"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "oddsFormat": "decimal"}
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"API error {r.status_code}: {r.text}")
    return r.json()

st.set_page_config(page_title="ENG Arb Finder — All comps", page_icon="⚽", layout="wide")
st.title("⚽ English Football Arbitrage Finder — All competitions on one screen")

# Timestamp (Europe/Dublin) for exports
tzname = "Europe/Dublin"
tz = ZoneInfo(tzname) if ZoneInfo else None
fetched_at = (datetime.now(tz) if tz else datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")
fetched_regions = None  # filled after sidebar

# Auto-refresh every 30 minutes while page is open
if "last_tick" not in st.session_state:
    st.session_state["last_tick"] = time.time()
elif time.time() - st.session_state["last_tick"] > 30*60:
    st.session_state["last_tick"] = time.time()
    st.experimental_rerun()

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("The Odds API key", type="password")
    comps = st.multiselect("Competitions", list(SPORT_KEYS.keys()), default=list(SPORT_KEYS.keys()))
    regions = st.multiselect("Regions (bookmaker regions)", ["uk","eu","us","au"], default=DEFAULT_REGIONS)
    fetched_regions = ",".join(regions)
    market_label = st.selectbox("Market", list(SUPPORTED_MARKETS.keys()), index=0)
    bankroll = st.number_input("Bankroll to allocate per bet", min_value=0.0, value=100.0, step=10.0)
    currency_symbol = st.text_input("Currency symbol", value="£")
    stake_step = st.selectbox("Stake rounding step", options=[0.01, 0.05, 0.10, 0.50, 1.00], index=1, format_func=lambda x: f"{x:.2f}")
    odds_decimals = st.selectbox("Odds decimal places", options=[2,3], index=1)
    show_equalized = st.checkbox("Include equalized payout line in betslip", value=True)
    min_roi = st.slider("Minimum ROI to show (percent)", min_value=-10.0, max_value=10.0, value=0.2, step=0.1)
    include_commission = st.checkbox("Include per‑book commission (optional)", value=False)
    filter_to_target = st.checkbox("Only show arbs incl. Paddy/Betfair/Sky", value=True)
    show_debug = st.checkbox("Show raw market keys (debug)", value=False)

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

if not api_key:
    st.info("Enter your API key in the sidebar to fetch live odds."); st.stop()

market_key = SUPPORTED_MARKETS[market_label]

# Fetch odds for all chosen competitions
all_records = []
fetch_errors = []
for comp in comps:
    sport_key = SPORT_KEYS[comp]
    try:
        events = fetch_odds(api_key, sport_key, regions, [market_key])
    except Exception as e:
        fetch_errors.append(f"{comp}: {e}")
        continue

    # Commission map inputs per comp (optional)
    if include_commission and events:
        all_books = sorted({b.get("title", b.get("key","")) for ev in events for b in ev.get("bookmakers",[]) })
        with st.sidebar:
            st.caption(f"Commission for books (visible in {comp})")
            for bk in all_books:
                key = f"commission_{comp}_{bk}"
                pct = st.number_input(f"{bk}", min_value=0.0, max_value=0.10, value=0.0, step=0.005, key=key)
                commission_map[bk] = pct

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
            # ----- 1X2 (Home/Draw/Away) -----
            needed = [home, "Draw", away]; name_map = {}
            for k in list(best.keys()):
                low = k.lower()
                if "draw" in low: name_map["Draw"] = best[k]
                elif home and home.lower() in low: name_map[home] = best[k]
                elif away and away.lower() in low: name_map[away] = best[k]
            if not all(x in name_map for x in needed):
                continue
            best_outcomes = [
                ("Home", name_map[home][0], name_map[home][1]),
                ("Draw", name_map["Draw"][0], name_map["Draw"][1]),
                ("Away", name_map[away][0], name_map[away][1]),
            ]

        elif market_key == "totals_corners":
            # ----- Over/Under Corners (two-way) -----
            best_ou = {}
            line_seen = None
            filter_corners = True
            match_token = "corner"
            # Optional debug: show market keys
            if show_debug:
                mk = sorted({m.get("key","") for b in ev.get("bookmakers",[]) for m in b.get("markets",[])})
                st.caption(f"Markets visible for {home} vs {away}: {mk}")
            for bk in ev.get("bookmakers", []):
                book_name = bk.get("title") or bk.get("key")
                for m in bk.get("markets", []):
                    mkey = m.get("key", "")
                    if mkey not in ("totals", "totals_corners", "corners", "total_corners", "corners_totals"):
                        continue
                    text_blob = " ".join([
                        str(m.get("key", "")),
                        str(m.get("last_update", "")),
                        str(m.get("outcomes", "")),
                        str(bk.get("key", "")),
                        str(bk.get("title", "")),
                    ]).lower()
                    if filter_corners and match_token not in text_blob:
                        continue
                    for o in m.get("outcomes", []):
                        name = (o.get("name") or "").strip()
                        price = float(o.get("price"))
                        point = o.get("point")
                        if name.lower() in ("over", "under"):
                            label = f"{name.title()} {point}" if point is not None else name.title()
                            if point is not None:
                                line_seen = point
                            if label not in best_ou or price > best_ou[label][0]:
                                best_ou[label] = (price, book_name)
            if not best_ou:
                continue
            ou_over = f"Over {line_seen}" if line_seen is not None else "Over"
            ou_under = f"Under {line_seen}" if line_seen is not None else "Under"
            if ou_over not in best_ou or ou_under not in best_ou:
                pairs = list(best_ou.keys())
                overs = [k for k in pairs if k.lower().startswith("over")]
                unders = [k for k in pairs if k.lower().startswith("under")]
                if not (overs and unders):
                    continue
                ou_over, ou_under = overs[0], unders[0]
            best_outcomes = [
                (ou_over,  best_ou[ou_over][0],  best_ou[ou_over][1]),
                (ou_under, best_ou[ou_under][0], best_ou[ou_under][1]),
            ]

        else:
            continue


        if filter_to_target:
            books_in_arb = {b for (_,_,b) in best_outcomes}
            if not any(is_target_book(b) for b in books_in_arb): continue

        implieds = [1.0/(o*(1-commission_map.get(b,0.0))) for (_,o,b) in best_outcomes]
        margin = 1.0 - sum(implieds)
        roi_est = max(margin*100.0, 0.0)

        if roi_est >= min_roi:
            plan_df, roi_pct, margin2 = stake_split_for_arbitrage(best_outcomes, bankroll, commission_map)
            # Add link column to the per-outcome plan and format columns
            match_str = f"{home} vs {away}"
            plan_df["Stake"] = plan_df["Stake"].apply(lambda v: round_stake(float(v), stake_step))
            plan_df["Odds"] = plan_df["Odds"].apply(lambda v: round(float(v), odds_decimals))
            plan_df["Net Payout if Wins"] = plan_df["Net Payout if Wins"].apply(lambda v: round(float(v), 2))
            links = [bookmaker_link(row["Bookmaker"], match_str) for _, row in plan_df.iterrows()]
            plan_df.insert(len(plan_df.columns), "Bookmaker Link", links)

            all_records.append({
                "Competition": comp,
                "Match": match_str,
                "Kickoff": commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else "",
                "Best Outcomes": [f"{lab}: {odds} @ {book}" for (lab,odds,book) in best_outcomes],
                
                
                "Arb Margin %": round(margin2*100, 3),
                "Plan": plan_df,
                "BetslipText": build_betslip_text(comp, match_str, (commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else ""), roi_pct, bankroll, plan_df, currency_symbol, stake_step, odds_decimals, show_equalized),
            })

# Display any fetch errors
if fetch_errors:
    with st.expander("Data fetch notes"):
        for e in fetch_errors:
            st.info(e)

# Combined summary table
st.subheader("Summary of opportunities (all selected competitions)")
if not all_records:
    msg = "No surebets found at the current thresholds"
    if filter_to_target: msg += " (filtered by bookmaker)."
    st.warning(msg + " Try lowering the ROI filter or refreshing.")
else:
    summary_df = pd.DataFrame([{
        "Competition": r["Competition"],
        "Match": r["Match"],
        "Kickoff": r["Kickoff"],
        "Market": market_label,
        "Best": " | ".join(r.get("Best Outcomes", [])) if isinstance(r.get("Best Outcomes", []), list) else r.get("Best Outcomes", ""),
        "Arb Margin %": r["Arb Margin %"],
    } for r in all_records]).sort_values(["Competition", "Kickoff", "Match"])
    st.dataframe(summary_df, use_container_width=True)

    # Per-match details grouped by competition
    st.subheader("Details")
    for comp in sorted(set(r["Competition"] for r in all_records)):
        st.markdown(f"### {comp}")
        comp_records = [r for r in all_records if r["Competition"] == comp]
        for rec in comp_records:
            with st.expander(f"{rec['Match']} — {rec['Kickoff']} — Margin {rec['Arb Margin %']}%"):
                c1,c2,c3 = st.columns(3)
                with c1: st.metric("Best Home", rec["Best Home"].split(" @ ")[0], help=rec["Best Home"].split(" @ ")[1])
                with c2: st.metric("Best Draw", rec["Best Draw"].split(" @ ")[0], help=rec["Best Draw"].split(" @ ")[1])
                with c3: st.metric("Best Away", rec["Best Away"].split(" @ ")[0], help=rec["Best Away"].split(" @ ")[1])
                st.dataframe(rec["Plan"], use_container_width=True)
                st.caption("Copy as betslip")
                st.code(rec["BetslipText"])

# CSV downloads with timestamp/regions + links (as before)
if all_records:
    # Summary
    summary_rows = [{
        "Competition": r["Competition"],
        "Match": r["Match"],
        "Kickoff": r["Kickoff"],
        "Best": " | ".join(r.get("Best Outcomes", [])) if isinstance(r.get("Best Outcomes", []), list) else r.get("Best Outcomes", ""),
        "Arb Margin %": r["Arb Margin %"],
        "Fetched At (Europe/Dublin)": fetched_at,
        "Regions": fetched_regions,
    } for r in all_records]
    export_summary_df = pd.DataFrame(summary_rows).sort_values(["Competition", "Kickoff", "Match"])

    # Detailed
    detailed_rows = []
    for r in all_records:
        plan_df = r["Plan"].copy()
        plan_df.insert(0, "Competition", r["Competition"])
        plan_df.insert(1, "Match", r["Match"])
        plan_df.insert(2, "Kickoff", r["Kickoff"])
        plan_df["Arb Margin %"] = r["Arb Margin %"]
        plan_df["Fetched At (Europe/Dublin)"] = fetched_at
        plan_df["Regions"] = fetched_regions
        detailed_rows.append(plan_df)

    export_detailed_df = pd.concat(detailed_rows, ignore_index=True) if detailed_rows else pd.DataFrame()
    if not export_detailed_df.empty:
        cols = ["Competition","Match","Kickoff","Arb Margin %","Outcome","Bookmaker","Bookmaker Link","Odds","Commission","Stake","Net Payout if Wins","Fetched At (Europe/Dublin)","Regions"]
        export_detailed_df = export_detailed_df[cols]

    st.download_button("⬇️ Download summary CSV", data=export_summary_df.to_csv(index=False).encode("utf-8"), file_name="surebets_summary_all_competitions.csv", mime="text/csv")
    st.download_button("⬇️ Download detailed CSV (per outcome + stakes + links)", data=export_detailed_df.to_csv(index=False).encode("utf-8"), file_name="surebets_detailed_all_competitions.csv", mime="text/csv")
