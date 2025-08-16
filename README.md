# ENG Arbitrage — Multi-competition, CSV export, and shareable Telegram betslips

## UI controls
  * Currency symbol
  * Stake rounding step (e.g., £0.05)
  * Odds decimals (2 or 3)
  * Toggle to include an Equalized payout line
  * Multi-select competitions: Premier League, Championship, League One, League Two
  * CSV export button for all arbs
  * Notification cadence: minutely 12:00–17:00 on a chosen day, otherwise every 30 mins

## Notifier variables
  * `BANKROLL` (default `100`)
  * `CURRENCY` (default `£`)
  * `STAKE_ROUND` (default `0.05`)
  * `SHOW_EQUALIZED_PAYOUT` (default `true`)
  * `MIN_ROI_SHARE` (default `5.0`) — only arbs at/above this include a shareable betslip block

The notifier still adds betslip blocks for arbs with ROI > 5% and respects your minutely time window gating.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
