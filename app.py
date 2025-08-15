"""
EPL Arbitrage Finder (Surebet Scanner)
Single‑file Streamlit app that compares bookmaker prices (via The Odds API)
for English football (EPL by default) and flags cross‑book arbitrage.

How to run locally:
  1) pip install streamlit requests pandas python-dateutil
  2) streamlit run app.py

Notes:
  • You need an API key from The Odds API (free tier available). Enter it in the sidebar.
  • This tool only RECOMMENDS stake splits for potential surebets. It does NOT place bets.
  • Always respect bookmaker & data‑provider terms. Odds move fast; refresh before acting.
  • Gambling involves risk. Use limits and only bet what you can afford to lose.
"""

import math
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from dateutil import parser as dtparser

# ------------------------------
# Utility
# ------------------------------

def implied_prob(decimal_odds: float, commission: float = 0.0) -> float:
    """Return implied probability from decimal odds, adjusting for commission (e.g., exchange fee).
    commission is expressed as a fraction (5% => 0.05). For sportsbooks, leave 0.
    We adjust payout by (1 - commission) so the effective odds are odds * (1 - commission).
    """
    if decimal_odds <= 1e-9:
        return float("inf")
    effective_odds = decimal_odds * (1 - commission)
    if effective_odds <= 1e-9:
        return float("inf")
    return 1.0 / effective_odds


def stake_split_for_arbitrage(best_odds: List[Tuple[str, float, str]], bankroll: float, commission_map: Dict[str, float]) -> Tuple[pd.DataFrame, float, float]:
    """Compute proportional stakes for arbitrage across N outcomes using best odds list.

    best_odds: List of tuples (outcome_key, decimal_odds, bookmaker).
    bankroll: total money to distribute across outcomes.
    commission_map: map bookmaker -> commission fraction (0..1). Missing defaults to 0.

    Returns a DataFrame (outcome, odds, bookmaker, stake, payout) and (roi_pct, margin)
    where margin = 1 - sum(implied_probs), roi_pct = (min(payout) - bankroll)/bankroll*100.
    """
    rows = []
    implieds = []
    for outcome, odds, book in best_odds:
        c = commission_map.get(book, 0.0)
        ip = implied_prob(odds, c)
        implieds.append(ip)
    total_ip = sum(implieds)
    margin = 1.0 - total_ip

    stakes = []
    payouts = []
    for (outcome, odds, book), ip in zip(best_odds, implieds):
        stake = bankroll * (ip / total_ip)
        c = commission_map.get(book, 0.0)
        payout = stake * odds * (1 - c)
        stakes.append(stake)
        payouts.append(payout)
        rows.append({
            "Outcome": outcome,
            "Bookmaker": book,
            "Odds": round(odds, 3),
            "Commission": f"{int(c*100)}%",
            "Stake": round(stake, 2),
            "Net Payout if Wins": round(payout, 2),
        })

    min_payout = min(payouts) if payouts else 0.0
    roi_pct = ((min_payout - bankroll) / bankroll * 100.0) if bankroll else 0.0
    df = pd.DataFrame(rows)
    return df, roi_pct, margin


# ------------------------------
# API client (The Odds API v4)
# ------------------------------

BASE_URL = "https://api.the-odds-api.com/v4"

SPORT_KEYS = {
    "English Premier League (EPL)": "soccer_epl",
    "EFL Championship": "soccer_efl_championship",
    "FA Cup": "soccer_fa_cup",
}

DEFAULT_REGIONS = ["uk", "eu"]  # focus on UK/EU books
SUPPORTED_MARKETS = {
    "Match Result (1X2)": "h2h",
    "Draw No Bet": "h2h_lay",  # not always available; some providers map differently
}


@st.cache_data(ttl=60)
def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    """Fetch odds snapshot for a sport. Returns list of events (matches) with bookmakers"""
    params = {
        "apiKey": api_key,
        "regions": ",".join(regions),
        "markets": ",".join(markets),
        "oddsFormat": "decimal",
    }
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"API error {r.status_code}: {r.text}")
    return r.json()


# ------------------------------
# Streamlit UI
# ------------------------------

st.set_page_config(page_title="EPL Arbitrage Finder", page_icon="⚽", layout="wide")
st.title("⚽ EPL Arbitrage Finder (Surebet Scanner)")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("The Odds API key", type="password")
    sport_label = st.selectbox("Competition", list(SPORT_KEYS.keys()), index=0)
    regions = st.multiselect("Regions (bookmaker regions)", ["uk", "eu", "us", "au"], default=DEFAULT_REGIONS)
    market_label = st.selectbox("Market", list(SUPPORTED_MARKETS.keys()), index=0)
    bankroll = st.number_input("Bankroll to allocate per bet (£)", min_value=0.0, value=100.0, step=10.0)
    min_roi = st.slider("Minimum ROI to show (percent)", min_value=-10.0, max_value=10.0, value=0.2, step=0.1)
    include_commission = st.checkbox("Include per‑book commission (optional)", value=False)

    commission_map: Dict[str, float] = {}
    if include_commission:
        st.caption("Set commission per bookmaker/exchange (0–10%). Leave blank for 0%.")

    st.divider()
    st.caption("Odds move quickly. Use the refresh button below before acting.")
    refresh = st.button("🔄 Refresh odds")

sport_key = SPORT_KEYS[sport_label]
market_key = SUPPORTED_MARKETS[market_label]

# Fetch odds
if not api_key:
    st.info("Enter your API key in the sidebar to fetch live odds.")
    st.stop()

try:
    events = fetch_odds(api_key, sport_key, regions, [market_key])
except Exception as e:
    st.error(f"Failed to fetch odds: {e}")
    st.stop()

# Build commission map inputs dynamically from bookmaker names present
if include_commission and events:
    all_books = sorted({b.get("title", b.get("key", "")) for ev in events for b in ev.get("bookmakers", [])})
    with st.sidebar:
        for bk in all_books:
            key = f"commission_{bk}"
            pct = st.number_input(f"{bk}", min_value=0.0, max_value=0.10, value=0.0, step=0.005, key=key)
            commission_map[bk] = pct

# Process events
records = []

for ev in events:
    home = ev.get("home_team")
    away = ev.get("away_team")
    commence_time = dtparser.parse(ev.get("commence_time")) if ev.get("commence_time") else None

    # Collect best odds per outcome across bookmakers for this event
    best: Dict[str, Tuple[float, str]] = {}  # outcome -> (odds, bookmaker)

    for bk in ev.get("bookmakers", []):
        book_name = bk.get("title") or bk.get("key")
        for market in bk.get("markets", []):
            if market.get("key") != market_key:
                continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name")  # usually home/draw/away names
                price = float(outcome.get("price"))
                if name not in best or price > best[name][0]:
                    best[name] = (price, book_name)

    # Require complete 1X2 set (Home/Draw/Away) for arbitrage check
    if market_key == "h2h":
        needed = [home, "Draw", away]
        # Map outcomes by attempting fuzzy match (some APIs use team names directly)
        # Build a normalized mapping
        name_map = {}
        for k in list(best.keys()):
            low = k.lower()
            if "draw" in low:
                name_map["Draw"] = best[k]
            elif home and home.lower() in low:
                name_map[home] = best[k]
            elif away and away.lower() in low:
                name_map[away] = best[k]
        if not all(x in name_map for x in needed):
            continue
        best_triplet = [
            ("Home", name_map[home][0], name_map[home][1]),
            ("Draw", name_map["Draw"][0], name_map["Draw"][1]),
            ("Away", name_map[away][0], name_map[away][1]),
        ]
    else:
        # For other markets, skip in this minimal demo
        continue

    # Compute margin and ROI using commissions
    implieds = [
        implied_prob(o, commission_map.get(b, 0.0)) for (_, o, b) in best_triplet
    ]
    total_ip = sum(implieds)
    margin = 1.0 - total_ip
    if margin <= 0:
        roi_est = 0.0
    else:
        # If you distribute bankroll proportionally, guaranteed ROI equals margin
        roi_est = margin * 100.0

    if roi_est >= min_roi:
        # Compute stake plan for the bankroll
        plan_df, roi_pct, margin2 = stake_split_for_arbitrage(best_triplet, bankroll, commission_map)
        records.append({
            "Match": f"{home} vs {away}",
            "Kickoff": commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else "",
            "Best Home": f"{best_triplet[0][1]} @ {best_triplet[0][2]}",
            "Best Draw": f"{best_triplet[1][1]} @ {best_triplet[1][2]}",
            "Best Away": f"{best_triplet[2][1]} @ {best_triplet[2][2]}",
            "Arb Margin %": round(margin2*100, 3),
            "Plan": plan_df,
        })

# Display
st.subheader("Results")

if not records:
    st.warning("No surebets found at the current thresholds. Try lowering the ROI filter or refreshing.")
else:
    for rec in records:
        with st.expander(f"{rec['Match']} — Kickoff {rec['Kickoff']} — Margin {rec['Arb Margin %']}%"):
            cols = st.columns(3)
            with cols[0]:
                st.metric("Best Home", rec["Best Home"].split(" @ ")[0], delta=None, help=rec["Best Home"].split(" @ ")[1])
            with cols[1]:
                st.metric("Best Draw", rec["Best Draw"].split(" @ ")[0], delta=None, help=rec["Best Draw"].split(" @ ")[1])
            with cols[2]:
                st.metric("Best Away", rec["Best Away"].split(" @ ")[0], delta=None, help=rec["Best Away"].split(" @ ")[1])
            st.dataframe(rec["Plan"], use_container_width=True)

# Download CSV of opportunities (flattened without the per‑match plan)
if records:
    flat = [
        {
            "Match": r["Match"],
            "Kickoff": r["Kickoff"],
            "Best Home": r["Best Home"],
            "Best Draw": r["Best Draw"],
            "Best Away": r["Best Away"],
            "Arb Margin %": r["Arb Margin %"],
        }
        for r in records
    ]
    csv = pd.DataFrame(flat).to_csv(index=False).encode("utf-8")
    st.download_button("Download summary CSV", data=csv, file_name="surebets_summary.csv", mime="text/csv")

st.divider()
with st.expander("How this works (math)"):
    st.markdown(
        """
        For a 3‑way market (Home/Draw/Away) with decimal prices \\(O_H, O_D, O_A\\),
        we compute **implied probabilities** as \\(p_i = 1 / (O_i \\times (1-\\text{commission}_i))\\).

        If \\(p_H + p_D + p_A < 1\\) the market is *overbroke* and an arbitrage exists.
        Stake each outcome proportionally to its implied probability:
        \\(s_i = B \\cdot p_i / (p_H + p_D + p_A)\\), so every outcome returns approximately the same **net payout**.

        The **arbitrage margin** is \\(1 - (p_H + p_D + p_A)\\), which equals the **guaranteed ROI** when staking as above (before slippage/limits).
        """
    )

with st.expander("Limitations & Tips"):
    st.markdown(
        """
        * Odds are snapshots and can change within seconds. Always refresh and double‑check inside the bookmaker app before placing bets.
        * Minimum/maximum stake limits and account restrictions can kill arbs.
        * This demo looks at 1X2 only. You can extend it to two‑way markets (e.g., Draw No Bet) or Asian handicaps.
        * Commission inputs let you approximate exchange fees.
        * Respect site ToS and your local laws.
        """
    )
