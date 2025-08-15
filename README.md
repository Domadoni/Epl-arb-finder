
# ENG Arbitrage — All-in-one UI + Minutely Notifier (window-gated)

This repo combines:
- **Streamlit UI** that aggregates EPL, Championship, League One, League Two, FA Cup, EFL Cup on a single screen (multi-select). Includes Telegram test + session alerts and optional 30‑min auto‑refresh while open.
- **GitHub Actions notifier** that runs every minute but only executes:
  - every minute between your configured window (e.g., **12:00–17:00 Europe/Dublin** on the date you set), and
  - every **30 minutes** outside that window.

## Deploy the UI (Streamlit Community Cloud)
1. Upload this repo to GitHub.
2. Deploy `app.py` via https://share.streamlit.io.
3. In the app sidebar, paste your **The Odds API** key. Optionally add Telegram token & chat id and click **Send test**.

## Enable notifications
In GitHub **Settings → Secrets and variables → Actions**:

**Secrets**
- `ODDS_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**Variables**
- `TIMEZONE` = `Europe/Dublin`
- `RAPID_WINDOW_START_ISO` = e.g. `2025-08-16T12:00:00`
- `RAPID_WINDOW_END_ISO`   = e.g. `2025-08-16T17:00:00`
- (Optional) `MIN_ROI_PCT` (default `0.2`), `REGIONS` (default `uk,eu`)

The workflow triggers every minute but the script gates itself to your window; outside the window it only runs on minute `00` and `30`.

## Notes
- Sport keys used (The Odds API): `soccer_epl`, `soccer_efl_championship`, `soccer_england_league1`, `soccer_england_league2`, `soccer_fa_cup`, `soccer_efl_cup`.
- Only 1X2 is scanned in this example; extend as needed.
- Keep your Telegram bot token **private**; never commit it to code.
