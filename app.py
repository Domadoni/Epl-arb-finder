import streamlit as st
from notifier import run_notifier
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

DEFAULT_BANKROLL = 100
DEFAULT_CURRENCY = "£"
DEFAULT_STAKE_ROUND = 0.05     # round to nearest 5p
DEFAULT_DECIMALS = 2
DEFAULT_SHOW_EQUALIZED = True
DEFAULT_MIN_ROI_NOTIFY = 5.0   # %

st.set_page_config(page_title="ENG Arbitrage Finder", layout="wide")

st.title("ENG Arbitrage Finder")
st.caption("English football arbs between selected bookmakers, with Telegram notifications.")

# --- Sidebar controls ---
with st.sidebar:
    st.subheader("Settings")
    currency = st.text_input("Currency symbol", value=DEFAULT_CURRENCY)
    bankroll = st.number_input("Bankroll", min_value=1.0, value=float(DEFAULT_BANKROLL), step=10.0)
    stake_round = st.number_input("Stake rounding step", min_value=0.01, value=float(DEFAULT_STAKE_ROUND), step=0.01, help="e.g., £0.05")
    odds_decimals = st.selectbox("Odds decimals", options=[2,3], index=0)
    show_equalized = st.toggle("Include equalized payout line", value=DEFAULT_SHOW_EQUALIZED)
    min_roi_notify = st.number_input("Min ROI% for Telegram share block", min_value=0.0, value=DEFAULT_MIN_ROI_NOTIFY, step=0.5)
    telegram_token = st.text_input("Telegram bot token", type="password", help="Enter here (stored only in session).")
    telegram_chat_id = st.text_input("Telegram chat ID", help="Your user or group/chat id.")

    st.markdown("---")
    st.subheader("Notification cadence")
    local_tz = pytz.timezone("Europe/Dublin")
    tomorrow = date.today() + timedelta(days=1)
    window_start = st.time_input("High-frequency start", value=time(12,0))
    window_end = st.time_input("High-frequency end", value=time(17,0))
    high_freq_minutes = st.number_input("High-frequency interval (minutes)", min_value=1, value=1)
    low_freq_minutes = st.number_input("Low-frequency interval (minutes)", min_value=1, value=30)
    target_day = st.date_input("Day for high-frequency window", value=tomorrow)

    st.markdown("---")
    st.subheader("Run")
    run_scan = st.button("Scan now")

st.markdown("### Competitions")
competitions = st.multiselect(
    "Choose one or more competitions",
    ["Premier League", "Championship", "League One", "League Two"],
    default=["Premier League", "Championship", "League One", "League Two"],
)

results_df = pd.DataFrame()
if run_scan:
    results_df = run_notifier(
        competitions=competitions,
        bankroll=bankroll,
        currency=currency,
        stake_round=stake_round,
        odds_decimals=odds_decimals,
        show_equalized=show_equalized,
        min_roi_share=min_roi_notify,
        telegram_token=telegram_token or None,
        telegram_chat_id=telegram_chat_id or None,
        schedule={
            "tz": "Europe/Dublin",
            "target_day": str(target_day),
            "window_start": window_start.strftime("%H:%M"),
            "window_end": window_end.strftime("%H:%M"),
            "high_freq_minutes": int(high_freq_minutes),
            "low_freq_minutes": int(low_freq_minutes),
        },
    )
    if results_df is not None and len(results_df):
        st.success(f"Found {len(results_df)} arb(s).")
        st.dataframe(results_df, use_container_width=True)
    else:
        st.info("No arbs found this scan.")

# --- CSV Export ---
if results_df is not None and len(results_df):
    csv_bytes = results_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download all arbs as CSV",
        data=csv_bytes,
        file_name="arbs.csv",
        mime="text/csv"
    )
