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
