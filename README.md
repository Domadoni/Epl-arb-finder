
# ENG Arbitrage — Streamlit UI + Telegram Notifier (Repo-ready)

This repository is ready to push straight to GitHub and deploy.

## Structure
- `app.py` — Streamlit UI (all English comps on one screen, CSV exports, betslip copy block)
- `requirements.txt` — Python deps for Streamlit Cloud
- `notifier.py` — Telegram background notifier (minutely with time-window gating; adds betslip blocks for ROI>5%)
- `.github/workflows/arb_notifier.yml` — Scheduled GitHub Action
- `.streamlit/secrets.toml.template` — Example secrets file for local dev
- `.gitignore` — Ignores local env files & artifacts
- `README.md` — You are here

## Quick start (GitHub + Streamlit Cloud)

1. **Create repo** on GitHub and upload these files (keep the folder structure).
2. In the repo, set **Settings → Secrets and variables → Actions**:

**Secrets**
- `ODDS_API_KEY` — your The Odds API key
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — your numeric chat id

**Variables** (tweak as you like)
- `MIN_ROI_PCT` = `0.2`
- `REGIONS` = `uk,eu`
- `TIMEZONE` = `Europe/Dublin`
- `RAPID_WINDOW_START_ISO` = `2025-08-16T12:00:00`
- `RAPID_WINDOW_END_ISO`   = `2025-08-16T17:00:00`
- `BANKROLL` = `100`
- `CURRENCY` = `£`
- `STAKE_ROUND` = `0.05`
- `SHOW_EQUALIZED_PAYOUT` = `true`

3. **Streamlit Cloud** → New App → point to `app.py` on this repo.
4. In Streamlit (optional) add **Secrets** (Settings → Secrets):
```toml
[telegram]
bot_token = "YOUR_BOT_TOKEN"
chat_id = "YOUR_CHAT_ID"
```
5. Open the app, paste your **Odds API key** in the sidebar, and you’re off.

## Local dev
- Create a virtualenv and install `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  streamlit run app.py
  ```
- To use Telegram test locally, copy `.streamlit/secrets.toml.template` to `.streamlit/secrets.toml` and fill it.

---

**Note:** Always confirm odds before staking; prices move and limits apply.


## Notifier thresholds
- `MIN_ROI_PCT` — **scan threshold** (arbs must be ≥ this to be collected).
- `MIN_ROI_PCT_NOTIFY` — **notification threshold** (arbs must be ≥ this to be sent to Telegram). If not set, it falls back to `MIN_ROI_PCT`.
