
# English Football Arbitrage Suite — EPL + Championship + League One + League Two

Includes:
- `app.py` — Streamlit UI (pick league in sidebar; optional Telegram alerts + 30‑min auto-refresh while open)
- `notifier.py` — GitHub Actions script scanning **EPL, Championship, League One, League Two** every 30 minutes
- `.github/workflows/arb_notifier.yml` — the 30‑minute schedule
- `requirements.txt` — app dependencies

## Streamlit deploy
1. Create a GitHub repo; upload these files.
2. Deploy to Streamlit Community Cloud → `app.py`.
3. Paste your **The Odds API** key in the sidebar. (Optional) add Telegram token/chat id and hit **Send test**.

## GitHub Actions notifier
1. In repo **Settings → Secrets and variables → Actions**, add:
   - `ODDS_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
2. (Optional) add `MIN_ROI_PCT` (default `0.2`) and `REGIONS` (default `uk,eu`).
3. The workflow runs every 30 minutes. You can also **Run workflow** manually.

## Notes
- Sport keys used (The Odds API): `soccer_epl`, `soccer_efl_championship`, `soccer_england_league1`, `soccer_england_league2`.
- Only 1X2 (h2h) is scanned in this example; extend to spreads/totals if you want.
- Optional filter to only show arbs with **Paddy Power / Betfair / Sky Bet**.
- Odds change quickly; always confirm prices before staking and respect limits/laws.
