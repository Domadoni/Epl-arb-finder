
# ENG Arbitrage — Tuned betslip formatting

**UI controls**
- Currency symbol
- Stake rounding step (e.g., £0.05)
- Odds decimals (2 or 3)
- Toggle to include an **Equalized payout** line

**Notifier variables**
- `BANKROLL` (default `100`)
- `CURRENCY` (default `£`)
- `STAKE_ROUND` (default `0.05`)
- `SHOW_EQUALIZED_PAYOUT` (default `true`)

The notifier still adds **betslip blocks** for arbs with **ROI > 5%** and respects your minutely time window gating.

> Tip: if your books only accept stakes to the nearest 5p/10c, set `STAKE_ROUND=0.05` (or 0.10).
