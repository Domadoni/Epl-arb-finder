import streamlit as st
import pandas as pd
import requests
from typing import Dict

st.set_page_config(page_title="ENG Arb Finder", layout="wide")

def norm_book(name: str) -> str:
    return name.strip().lower()

def is_betfair_exchange(name: str) -> bool:
    return "betfair" in norm_book(name)

DEFAULT_PARTNER_BOOKS = {"bet365","ladbrokes","william hill","boylesports","boyle sports","coral"}
def is_partner_book(name: str, partner_set:set) -> bool:
    return any(p in norm_book(name) for p in partner_set)


with st.sidebar:
    st.header("⚙️ Settings")
    # Load defaults from Streamlit secrets if available
    try:
        default_api_key = st.secrets.get('odds_api', {}).get('api_key', '')
    except Exception:
        default_api_key = ''
    try:
        default_bot_token = st.secrets.get('telegram', {}).get('bot_token', '')
        default_chat_id = st.secrets.get('telegram', {}).get('chat_id', '')
    except Exception:
        default_bot_token = ''
        default_chat_id = ''
    api_key = st.text_input("Odds API Key", value=default_api_key, type="password")
    restrict_allowed = st.checkbox("Restrict to specific bookmakers", value=False)
    betfair_pair_only = st.checkbox("Require Betfair Exchange + one partner (two-way only)", value=False)
    partner_options = ["Bet365","Ladbrokes","William Hill","BoyleSports","Coral"]
    selected_partners = st.multiselect("Betfair partner bookmakers", partner_options, default=partner_options)
    partner_norm = {s.strip().lower() for s in selected_partners} if selected_partners else set()
    allowed_books = st.multiselect("Allowed bookmakers", list(DEFAULT_PARTNER_BOOKS), default=list(DEFAULT_PARTNER_BOOKS))

    st.subheader("Filters")
    min_roi = st.slider("Minimum ROI to show (percent)", 0.0, 20.0, 0.5, 0.1)
    min_roi_notify = st.slider("Minimum ROI to notify (percent)", 0.0, 20.0, 5.0, 0.1)

    st.subheader("🔔 Telegram alerts (optional)")
    bot_token = st.text_input("Bot token", value=default_bot_token, type="password", help="Create via @BotFather")
    chat_id = st.text_input("Chat ID", value=default_chat_id, help="Your user or group chat id")
    notify_live = st.checkbox("Notify when new arbs appear", value=False)
    if st.button("Send test"):
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": "✅ Test from ENG Arb Finder","parse_mode":"HTML"},
                timeout=15
            ).raise_for_status()
            st.success("Test sent (check Telegram).")
        except Exception as e:
            st.warning(f"Telegram send failed: {e}")

if not api_key:
    st.stop()

st.title("ENG Arb Finder")
st.write("This is a placeholder demo UI. Odds fetching & arb logic plug in here.")

# Dummy example table
df = pd.DataFrame([
    {"Competition":"EPL","Match":"Team A vs Team B","Kickoff":"2025-08-17 15:00",
     "Best Home":"2.10 @ Betfair","Best Away":"1.90 @ Bet365","Arb Margin %":4.2}
])
st.dataframe(df)

# Telegram notify placeholder
if bot_token and chat_id and notify_live:
    arbs_to_notify = [r for _,r in df.iterrows() if r["Arb Margin %"] >= min_roi_notify]
    if arbs_to_notify:
        lines = [f"Arb found: {r['Match']} {r['Arb Margin %']}%" for _,r in df.iterrows()]
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text":"\n".join(lines)},
                timeout=15
            )
            st.toast("Telegram notification sent ✅")
        except Exception as e:
            st.warning(f"Telegram send failed: {e}")
