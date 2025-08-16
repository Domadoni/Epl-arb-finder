# ENG Arb Finder

Streamlit app + GitHub Actions notifier for English football arbitrage.

## Features
- 1X2 + Corners Over/Under
- Betfair+Partner filter (configurable)
- Allowed bookmakers multiselect (no presets)
- Telegram alerts (with separate notify ROI threshold)
- CSV export & betslip block
- Background notifier via GitHub Actions

## GitHub Variables
- `MIN_ROI_PCT`
- `MIN_ROI_PCT_NOTIFY`
- `ALLOWED_BOOKMAKERS`
- `REQUIRE_BETFAIR_PAIR`
- `PARTNER_BOOKS`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`


## Streamlit secrets
Local dev: copy `.streamlit/secrets.toml.template` to `.streamlit/secrets.toml` and populate the values.
- `[telegram] bot_token`, `chat_id`
- `[odds_api] api_key`


## Mobile-friendly GitHub deploy
1. Download this ZIP and extract it on your phone.
2. In GitHub (mobile web/app), create a new repo and upload all files/folders (keep structure).
3. In the repo → **Settings → Secrets and variables → Actions**:
   - **Secrets:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (optional for alerts)
   - **Variables:** set thresholds & filters as needed (see above).
4. For Streamlit Cloud, connect the repo and set the same env as needed.
5. To use local Streamlit secrets, copy `.streamlit/secrets.toml.template` to `.streamlit/secrets.toml`.
