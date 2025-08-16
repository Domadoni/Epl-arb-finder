
"""
ENG Arbitrage — All competitions on one screen
Features:
- Markets: 1X2 and Corners Over/Under
- Generic "Best Outcomes" rendering (works for both markets)
- CSV exports (summary + detailed)
- Betslip copy block
- Debug toggle to inspect market keys
- Allowed bookmakers filter (with "UK Big 6" preset)
- Betfair+Partner filter (two-way only) with configurable partner list
- In-app Telegram: "Minimum ROI to notify" slider + digest
"""
from typing import Dict, List, Tuple
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

import hashlib, json, urllib.parse
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

SUPPORTED_MARKETS = {
    "Match Result (1X2)": "h2h",
    "Corners Over/Under": "totals_corners",
}

DEFAULT_REGIONS = ["uk", "eu"]
TARGET_BOOK_KEYWORDS = {"paddy power", "paddypower", "betfair", "sky bet", "skybet"}
BOOKMAKER_BASELINKS = [
    ("paddy power", "https://www.paddypower.com/"),
    ("betfair", "https://www.betfair.com/exchange/plus/"),
    ("sky bet", "https://m.skybet.com/"),
    ("skybet", "https://m.skybet.com/"),
]

# --- Allowed bookmakers filter ---
DEFAULT_ALLOWED_BOOKS = [
    "Bet365", "Ladbrokes", "William Hill", "Pinnacle", "Unibet", "Coral"
]
def ALLOWED_BOOK_NORMALIZE(name: str) -> str:
    n = (name or "").strip().lower()
    n = n.replace("ladbrook", "ladbroke").replace("ladbrooks", "ladbrokes")
    n = n.replace("uni bet", "unibet")
    return n

ALLOWED_BOOKS_CANON = {
    "bet365": {"bet365"},
    "ladbrokes": {"ladbroke", "ladbrokes"},
    "william hill": {"william hill", "williamhill", "will hill"},
    "pinnacle": {"pinnacle", "pinny"},
    "unibet": {"unibet", "uni bet"},
    "coral": {"coral"},
}
def is_allowed_book(name: str, allowed_set_norm: set) -> bool:
    ln = ALLOWED_BOOK_NORMALIZE(name)
    if ln in allowed_set_norm:
        return True
    for canon, variants in ALLOWED_BOOKS_CANON.items():
        if ln in variants and canon in allowed_set_norm:
            return True
    return False

# --- Betfair + Partner helpers (two-way only) ---
BETFAIR_KEYS = {"betfair", "betfair exchange"}
def norm_book(n: str) -> str:
    n = (n or "").strip().lower()
    n = n.replace("ladbrook","ladbroke").replace("ladbrooks","ladbrokes")
    n = n.replace("will hill","william hill")
    n = n.replace("boyle sports","boylesports").replace("boyle-sports","boylesports")
    n = n.replace("uni bet","unibet")
    return n
def is_betfair_exchange(name: str) -> bool:
    ln = norm_book(name)
    return any(k in ln for k in BETFAIR_KEYS)
def is_partner_book(name: str, partner_set: set) -> bool:
    ln = norm_book(name)
    return any(p in ln for p in partner_set)

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

def hash_arbs_summary(arbs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(arbs, sort_keys=True).encode("utf-8")).hexdigest()

def stake_split_for_arbitrage(best_odds: List[Tuple[str, float, str]], bankroll: float, commission_map: Dict[str, float]):
    rows = []
    implieds = []
    for outcome, odds, book in best_odds:
        c = commission_map.get(book, 0.0)
        ip = 1.0 / (odds * (1 - c)) if odds > 0 else float("inf")
        implieds.append(ip)
    total_ip = sum(implieds) or 1.0
    margin = 1.0 - total_ip
    payouts = []
    for (outcome, odds, book), ip in zip(best_odds, implieds):
        stake = bankroll * (ip / total_ip)
        c = commission_map.get(book, 0.0)
        payout = stake * odds * (1 - c)
        payouts.append(payout)
        rows.append({
            "Outcome": outcome,
            "Bookmaker": book,
            "Odds": round(odds,3),
            "Commission": f"{int(c*100)}%",
            "Stake": round(stake,2),
            "Net Payout if Wins": round(payout,2)
        })
    min_payout = min(payouts) if payouts else 0.0
    roi_pct = ((min_payout - bankroll) / bankroll * 100.0) if bankroll else 0.0
    import pandas as pd
    return pd.DataFrame(rows), roi_pct, margin

def build_betslip_text(comp: str, match_str: str, kickoff: str, market: str, roi_pct: float, bankroll: float, plan_df: pd.DataFrame) -> str:
    lines = [
        f"Betslip — {comp} ({market})",
        f"{match_str} (KO {kickoff})",
        f"Bankroll: £{bankroll:.2f}  |  ROI≈ {roi_pct:.2f}%",
        "-"*44
    ]
    for _, row in plan_df.iterrows():
        lines.append(f"{row['Outcome']:<12} @ {row['Bookmaker'][:18]:<18}  {row['Odds']:<5}  £{row['Stake']:.2f}")
    return "\n".join(lines)

def telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    if not bot_token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        st.warning(f"Telegram send failed: {e}")

@st.cache_data(ttl=60)
def fetch_odds(api_key: str, sport_key: str, regions: List[str], markets: List[str]) -> List[dict]:
    params = {"apiKey": api_key, "regions": ",".join(regions), "markets": ",".join(markets), "oddsFormat": "decimal"}
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    r = requests.get(url, params=params, timeout=25)
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

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("The Odds API key", type="password")
    comps = st.multiselect("Competitions", list(SPORT_KEYS.keys()), default=list(SPORT_KEYS.keys()))
    regions = st.multiselect("Regions (bookmaker regions)", ["uk","eu","us","au"], default=DEFAULT_REGIONS)
    fetched_regions = ",".join(regions)
    market_label = st.selectbox("Market", list(SUPPORTED_MARKETS.keys()), index=0)
    bankroll = st.number_input("Bankroll to allocate per bet (£)", min_value=0.0, value=100.0, step=10.0)
    min_roi_notify = st.slider("Minimum ROI to notify (percent)", min_value=-10.0, max_value=10.0, value=2.0, step=0.1)
    min_roi = st.slider("Minimum ROI to show (percent)", min_value=-10.0, max_value=10.0, value=0.2, step=0.1)
    filter_to_target = st.checkbox("Only show arbs incl. Paddy/Betfair/Sky", value=True)
    restrict_allowed = st.checkbox('Restrict to specific bookmakers', value=False)
    # Preset + multiselect    allowed_books = st.multiselect('Allowed bookmakers', DEFAULT_ALLOWED_BOOKS, default=DEFAULT_ALLOWED_BOOKS)
    # Betfair + Partner (two-way only)
    betfair_pair_only = st.checkbox('Require Betfair Exchange + one partner (two-way only)', value=False)
    partner_options = ['Bet365','Ladbrokes','William Hill','BoyleSports','Coral']
    selected_partners = st.multiselect('Betfair partner bookmakers', partner_options, default=partner_options)
    partner_norm = {s.strip().lower() for s in selected_partners} if selected_partners else set()

    show_debug = st.checkbox("Show raw market keys (debug)", value=False)

    commission_map: Dict[str, float] = {}

if not api_key:
    st.info("Enter your API key in the sidebar to fetch live odds."); st.stop()

market_key = SUPPORTED_MARKETS[market_label]

all_records = []
fetch_errors = []
for comp in comps:
    sport_key = SPORT_KEYS[comp]
    try:
        events = fetch_odds(api_key, sport_key, regions, [market_key if market_key != "totals_corners" else "totals"])
    except Exception as e:
        fetch_errors.append(f"{comp}: {e}")
        continue
    for ev in events:
        home = ev.get("home_team"); away = ev.get("away_team")
        commence_time = dtparser.parse(ev.get("commence_time")) if ev.get("commence_time") else None

        best = {}
        for bk in ev.get("bookmakers", []):
            book_name = bk.get("title") or bk.get("key")
            for market in bk.get("markets", []):
                mkey = market.get("key")
                if market_key == "h2h" and mkey != "h2h":
                    continue
                if market_key == "totals_corners" and mkey not in ("totals","totals_corners","corners","total_corners","corners_totals"):
                    continue
                for outcome in market.get("outcomes", []):
                    name = (outcome.get("name") or "").strip()
                    price = float(outcome.get("price"))
                    if name not in best or price > best[name][0]:
                        best[name] = (price, book_name, outcome.get("point"))

        if market_key == "h2h":
            needed = [home, "Draw", away]; name_map = {}
            for k, v in best.items():
                low = k.lower()
                if "draw" in low: name_map["Draw"] = v
                elif home and home.lower() in low: name_map[home] = v
                elif away and away.lower() in low: name_map[away] = v
            if not all(x in name_map for x in needed): 
                continue
            best_outcomes = [
                ("Home", name_map[home][0], name_map[home][1]),
                ("Draw", name_map["Draw"][0], name_map["Draw"][1]),
                ("Away", name_map[away][0], name_map[away][1]),
            ]
        elif market_key == "totals_corners":
            looks_like_corners = any("corner" in str(x).lower() for x in [best.keys(), ev.get("bookmakers", [])])
            if not looks_like_corners and show_debug:
                st.caption(f"Skipping non-corners totals for {home} vs {away}")
                continue
            line = None
            for nm, (_, _, pt) in best.items():
                if isinstance(pt, (int, float)):
                    line = pt; break
            over_label = f"Over {line}" if line is not None else "Over"
            under_label = f"Under {line}" if line is not None else "Under"
            if over_label not in best:
                overs = [k for k in best if k.lower().startswith("over")]
                if overs: over_label = overs[0]
            if under_label not in best:
                unders = [k for k in best if k.lower().startswith("under")]
                if unders: under_label = unders[0]
            if over_label not in best or under_label not in best:
                continue
            best_outcomes = [
                (over_label, best[over_label][0], best[over_label][1]),
                (under_label, best[under_label][0], best[under_label][1]),
            ]
        else:
            continue

        # Target-book filter
        if filter_to_target:
            books_in_arb = {b for (_,_,b) in best_outcomes}
            if not any(is_target_book(b) for b in books_in_arb):
                continue

        # Allowed-books restriction (preset or custom)
        if restrict_allowed:
            eff_books = allowed_books
            allowed_norm = {ALLOWED_BOOK_NORMALIZE(x) for x in eff_books}
            if not all(is_allowed_book(b, allowed_norm) for (_,_,b) in best_outcomes):
                continue

        # Betfair+Partner restriction (two-way markets only)
        if betfair_pair_only and market_key != 'h2h':
            partners = partner_norm if partner_norm else {"bet365","ladbrokes","william hill","boylesports","boyle sports","coral"}
            if len(best_outcomes) == 2:
                b1 = best_outcomes[0][2]; b2 = best_outcomes[1][2]
                cond = (is_betfair_exchange(b1) and is_partner_book(b2, partners)) or (is_betfair_exchange(b2) and is_partner_book(b1, partners))
                if not cond:
                    continue

        # arb math
        implieds = [1.0/(o*(1-commission_map.get(b,0.0))) for (_,o,b) in best_outcomes]
        margin = 1.0 - sum(implieds)
        roi_est = max(margin*100.0, 0.0)
        if roi_est < min_roi:
            continue

        plan_df, roi_pct, margin2 = stake_split_for_arbitrage(best_outcomes, bankroll, commission_map)
        match_str = f"{home} vs {away}"
        best_strs = [f"{lab}: {odds} @ {book}" for (lab,odds,book) in best_outcomes]
        all_records.append({
            "Competition": comp,
            "Match": match_str,
            "Kickoff": commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else "",
            "Market": market_label,
            "Best Outcomes": best_strs,
            "Arb Margin %": round(margin2*100, 3),
            "Plan": plan_df,
            "BetslipText": build_betslip_text(comp, match_str, (commence_time.strftime("%Y-%m-%d %H:%M") if commence_time else ""), market_label, roi_pct, bankroll, plan_df),
        })

# Display fetch errors
if fetch_errors:
    with st.expander("Data fetch notes"):
        for e in fetch_errors: st.info(e)

# Summary table
st.subheader("Summary of opportunities (all selected competitions)")
if not all_records:
    st.warning("No surebets found at the current thresholds. Try lowering the ROI filter or refreshing.")
else:
    summary_df = pd.DataFrame([{
        "Competition": r["Competition"],
        "Match": r["Match"],
        "Kickoff": r["Kickoff"],
        "Market": r["Market"],
        "Best": " | ".join(r["Best Outcomes"]),
        "Arb Margin %": r["Arb Margin %"],
    } for r in all_records]).sort_values(["Competition", "Kickoff", "Match"])
    st.dataframe(summary_df, use_container_width=True)

    # Details
    st.subheader("Details")
    for comp in sorted(set(r["Competition"] for r in all_records)):
        st.markdown(f"### {comp}")
        for rec in [r for r in all_records if r["Competition"] == comp]:
            with st.expander(f"{rec['Match']} — {rec['Kickoff']} — {rec['Market']} — Margin {rec['Arb Margin %']}%"):
                st.markdown("**Best prices:** " + " | ".join(rec["Best Outcomes"]))
                st.dataframe(rec["Plan"], use_container_width=True)
                st.caption("Copy as betslip")
                st.code(rec["BetslipText"])

# --- In-app Telegram notifications (session-based) ---
if "last_arb_digest_notify" not in st.session_state:
    st.session_state["last_arb_digest_notify"] = ""

if bot_token and chat_id and notify_live:
    arbs_to_notify = [r for r in all_records if r["Arb Margin %"] >= min_roi_notify]
    if arbs_to_notify:
        payload = [{k: r[k] for k in ("Competition","Match","Kickoff","Market","Arb Margin %")} for r in arbs_to_notify]
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        if digest != st.session_state["last_arb_digest_notify"]:
            lines = [f"<b>New arbs ≥ {min_roi_notify:.1f}%</b>"]
            comps = sorted(set(r["Competition"] for r in arbs_to_notify))
            shown = 0
            for comp in comps:
                lines.append(f"\n<b>{comp}</b>")
                chunk = [r for r in arbs_to_notify if r["Competition"] == comp][:5]
                for r in chunk:
                    lines.append(f"• [{r['Market']}] {r['Match']} — ROI ~ {r['Arb Margin %']}%")
                    for s in r["Best Outcomes"][:2]:
                        lines.append(f"  {s}")
                    shown += 1
                    if shown >= 12: break
                if shown >= 12: break
            telegram_send(bot_token, chat_id, "\n".join(lines))
            st.session_state["last_arb_digest_notify"] = digest
            st.toast("Telegram notification sent ✅", icon="✅")

# CSV downloads
if all_records:
    export_summary_df = pd.DataFrame([{
        "Competition": r["Competition"],
        "Match": r["Match"],
        "Kickoff": r["Kickoff"],
        "Market": r["Market"],
        "Best": " | ".join(r["Best Outcomes"]),
        "Arb Margin %": r["Arb Margin %"],
        "Fetched At (Europe/Dublin)": fetched_at,
        "Regions": fetched_regions,
    } for r in all_records]).sort_values(["Competition", "Kickoff", "Match"])

    detailed_rows = []
    for r in all_records:
        plan_df = r["Plan"].copy()
        plan_df.insert(0, "Competition", r["Competition"])
        plan_df.insert(1, "Match", r["Match"])
        plan_df.insert(2, "Kickoff", r["Kickoff"])
        plan_df.insert(3, "Market", r["Market"])
        plan_df["Arb Margin %"] = r["Arb Margin %"]
        plan_df["Fetched At (Europe/Dublin)"] = fetched_at
        plan_df["Regions"] = fetched_regions
        detailed_rows.append(plan_df)

    export_detailed_df = pd.concat(detailed_rows, ignore_index=True)
    cols = ["Competition","Match","Kickoff","Market","Arb Margin %","Outcome","Bookmaker","Odds","Commission","Stake","Net Payout if Wins","Fetched At (Europe/Dublin)","Regions"]
    export_detailed_df = export_detailed_df[cols]

    st.download_button("⬇️ Download summary CSV", data=export_summary_df.to_csv(index=False).encode("utf-8"), file_name="surebets_summary_all_competitions.csv", mime="text/csv")
    st.download_button("⬇️ Download detailed CSV (per outcome + stakes)", data=export_detailed_df.to_csv(index=False).encode("utf-8"), file_name="surebets_detailed_all_competitions.csv", mime="text/csv")
