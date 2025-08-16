
# --- AUTO-DISCOVERY OF EXISTING FUNCTIONS ---
import importlib

def _find_first(callables):
    """callables: list of (module_path, func_name). Return first found callable or None."""
    for mod, fn in callables:
        try:
            m = importlib.import_module(mod)
            if hasattr(m, fn):
                return getattr(m, fn)
        except Exception:
            continue
    return None

# Try common places/names you might have used
_fetch_odds = _find_first([
    ("odds", "fetch_odds"),
    ("odds", "get_odds"),
    ("data", "fetch_odds"),
    ("data", "get_odds"),
    ("scrapers", "fetch_odds"),
    ("scrapers", "get_odds"),
    ("engine", "fetch_odds"),
    ("engine", "get_odds"),
])

_find_arbs = _find_first([
    ("arbs", "find_arbs"),
    ("arb", "find_arbs"),
    ("engine", "find_arbs"),
    ("core", "find_arbs"),
])

if _fetch_odds is None or _find_arbs is None:
    # You can also hard-code your actual import here once you know it:
    # from my_module import my_fetch as _fetch_odds, my_arbs as _find_arbs
    missing = []
    if _fetch_odds is None: missing.append("fetch_odds")
    if _find_arbs is None: missing.append("find_arbs")
    raise RuntimeError(
        "Missing core functions: {}. Either:\n"
        "  • Rename your existing functions to these names, or\n"
        "  • Import them in notifier.py and assign:\n"
        "      _fetch_odds = your_real_fetch\n"
        "      _find_arbs = your_real_find_arbs\n".format(", ".join(missing))
    )
    
import requests
from typing import List, Dict, Any, Tuple
from datetime import datetime, date, time, timedelta
import pytz
import math
import pandas as pd

# --- Your existing helpers here ---
# def fetch_odds(competitions: List[str]) -> pd.DataFrame: ...
# def find_arbs(odds_df: pd.DataFrame) -> pd.DataFrame: ...

def send_telegram(token: str, chat_id: str, text: str):
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

def _round_to_step(x: float, step: float) -> float:
    return round(round(x / step) * step + 1e-9, 2)

def _fmt_betslip(row: pd.Series, currency: str, bankroll: float, stake_round: float,
                 odds_decimals: int, show_equalized: bool) -> str:
    """Builds a shareable betslip-style block for a single arb row."""
    event = f"{row.get('home_team','?')} vs {row.get('away_team','?')}"
    market = row.get('market', '1X2')
    book_a = row.get('book_a','A')
    book_b = row.get('book_b','B')
    oa = float(row.get('odds_a', 0))
    ob = float(row.get('odds_b', 0))
    sa = _round_to_step(float(row.get('stake_a', 0)), stake_round)
    sb = _round_to_step(float(row.get('stake_b', 0)), stake_round)
    roi = float(row.get('roi', 0))
    payout_eq = float(row.get('payout_equalized', 0.0))

    fmt = f"{{:.{odds_decimals}f}}"
    lines = []
    lines.append("🔁 <b>Arb Opportunity</b>")
    lines.append(f"Match: {event} • Market: {market}")
    lines.append(f"{book_a}: Odds {fmt.format(oa)} — Stake {currency}{sa}")
    lines.append(f"{book_b}: Odds {fmt.format(ob)} — Stake {currency}{sb}")
    lines.append(f"ROI: {roi:.2f}%")
    if show_equalized and payout_eq > 0:
        lines.append(f"Equalized Payout: {currency}{payout_eq:.2f}")
    return "\n".join(lines)

def _within_window(now: datetime, target_day: date, start_hm: Tuple[int,int], end_hm: Tuple[int,int]) -> bool:
    return now.date() == target_day and (time(*start_hm) <= now.time() <= time(*end_hm))

def run_notifier(
    competitions: List[str],
    bankroll: float,
    currency: str,
    stake_round: float,
    odds_decimals: int,
    show_equalized: bool,
    min_roi_share: float,
    telegram_token: str | None,
    telegram_chat_id: str | None,
    schedule: Dict[str, Any] | None = None,
) -> "pd.DataFrame":
    """Fetch odds for selected competitions, compute arbs, notify via Telegram, and return DataFrame."""
    odds = fetch_odds(competitions)
    arbs = find_arbs(odds)
    if arbs is None or len(arbs) == 0:
        return arbs

    if telegram_token and telegram_chat_id:
        shareable = []
        for _, row in arbs.iterrows():
            if float(row.get("roi", 0)) >= float(min_roi_share):
                shareable.append(
                    _fmt_betslip(
                        row,
                        currency=currency,
                        bankroll=bankroll,
                        stake_round=stake_round,
                        odds_decimals=odds_decimals,
                        show_equalized=show_equalized,
                    )
                )
        if shareable:
            msg = "\n\n".join(shareable)
            if schedule:
                tz = pytz.timezone(schedule.get("tz","Europe/Dublin"))
                now = datetime.now(tz)
                tgt = date.fromisoformat(schedule.get("target_day"))
                sh, sm = map(int, schedule.get("window_start","12:00").split(":"))
                eh, em = map(int, schedule.get("window_end","17:00").split(":"))
                hi = int(schedule.get("high_freq_minutes", 1))
                lo = int(schedule.get("low_freq_minutes", 30))
                in_window = _within_window(now, tgt, (sh, sm), (eh, em))
                interval = hi if in_window else lo
                if now.minute % interval == 0:
                    send_telegram(telegram_token, telegram_chat_id, msg)
            else:
                send_telegram(telegram_token, telegram_chat_id, msg)

    return arbs
