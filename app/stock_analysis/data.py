"""
Shared market data fetching (yfinance) and watchlist rule configuration.
Used by both Lambda handlers and the local report generator script.
"""
import json
import logging
import os
import warnings
from datetime import datetime, timedelta
from typing import Dict, List

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_company_names() -> Dict[str, str]:
    """Load company names from the static JSON file bundled with the package."""
    path = os.path.join(_DATA_DIR, "company_names.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load company_names.json: %s", exc)
        return {}


COMPANY_NAMES: Dict[str, str] = _load_company_names()


def load_watchlists(table_name: str) -> Dict[str, Dict]:
    """Load watchlist definitions from DynamoDB (version="latest" items).

    Each item must have: watchlistId (str), version="latest", name (str), tickers (list[str]).
    Returns the same shape as the old WATCHLISTS constant.
    """
    import boto3
    from boto3.dynamodb.conditions import Attr

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    response = table.scan(FilterExpression=Attr("version").eq("latest"))
    items = list(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression=Attr("version").eq("latest"),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    watchlists: Dict[str, Dict] = {}
    for item in items:
        wl_id = item["watchlistId"]
        watchlists[wl_id] = {
            "name": item["name"],
            "tickers": list(item["tickers"]),
        }

    logger.info("Loaded %d watchlists from %s", len(watchlists), table_name)
    return watchlists

RULE_CONFIGS: Dict[str, Dict] = {
    "ma_stack": {
        "name": "MA Stack",
        "priority": "high",
        "weight": 1.5,  # Volume/Confirmation: trend structure quality
        "rule_summary": "All MAs aligned bullishly and RSI not overheated — close > EMA-20 > SMA-50, RSI < 75",
        "rule_def": {
            "logic": "and",
            "name": "Bullish MA Stack",
            "description": "Price above EMA-20, EMA-20 above SMA-50, RSI below 75 — full bullish MA alignment without being overbought.",
            "source_text": "Flag names where close > EMA-20 > SMA-50 and RSI < 75 — all MAs stacked bullishly, not overheated.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "ema_20"},
                {"field": "ema_20", "op": ">", "value_from": "sma_50"},
                {"field": "rsi_14", "op": "<", "value": 75},
            ],
        },
    },
    "golden_cross": {
        "name": "Golden Cross",
        "priority": "high",
        "weight": 2.0,  # Primary Momentum: trend continuation breakout
        "rule_summary": "SMA-20 just crossed above SMA-50 today (was below yesterday) with price follow-through",
        "rule_def": {
            "logic": "and",
            "name": "Golden Cross",
            "description": "SMA-20 crossed above SMA-50 today (prev day SMA-20 was <= SMA-50) — fresh crossover with price above SMA-20 and RSI in healthy range.",
            "source_text": "Find names where SMA-20 crossed above SMA-50 today (prev_sma_20 <= prev_sma_50), close > SMA-20, and RSI < 70 — fresh golden cross with price follow-through.",
            "conditions": [
                {"field": "sma_20", "op": ">", "value_from": "sma_50"},
                {"field": "prev_sma_20", "op": "<=", "value_from": "prev_sma_50"},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": "<", "value": 70},
            ],
        },
    },
    "dead_cross": {
        "name": "Dead Cross",
        "priority": "high",
        "weight": 1.0,  # Structural/Risk: bearish regime signal — lower weight avoids over-ranking short setups
        "rule_summary": "SMA-20 just crossed below SMA-50 today (was above yesterday) with price breaking down",
        "rule_def": {
            "logic": "and",
            "name": "Dead Cross",
            "description": "SMA-20 crossed below SMA-50 today (prev day SMA-20 was >= SMA-50) — fresh bearish crossover with price below SMA-20.",
            "source_text": "Find names where SMA-20 crossed below SMA-50 today (prev_sma_20 >= prev_sma_50) and close < SMA-20 — fresh dead cross with price breaking down.",
            "conditions": [
                {"field": "sma_20", "op": "<", "value_from": "sma_50"},
                {"field": "prev_sma_20", "op": ">=", "value_from": "prev_sma_50"},
                {"field": "close", "op": "<", "value_from": "sma_20"},
            ],
        },
    },
    "ath_breakout": {
        "name": "ATH Breakout",
        "priority": "high",
        "weight": 2.0,  # Primary Momentum: strongest trend continuation signal
        "rule_summary": "Price at or above 52-week high with volume at least 1.5x the 20-day average",
        "rule_def": {
            "logic": "and",
            "name": "ATH Breakout",
            "description": "Flag tickers where price breaches the 52-week high on accumulating volume (≥1.5× avg).",
            "source_text": "Flag the ticker when volume accumulates and the price breaches all-time high.",
            "conditions": [
                {"field": "close", "op": ">=", "value_from": "high_52w"},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "near_ath": {
        "name": "Near-ATH Consolidation",
        "priority": "high",
        "weight": 1.0,  # Tactical/Minor: passive observation, needs confirmation
        "rule_summary": "Within 3% of 52-week high, quiet volume, RSI not overheated — coiling before breakout",
        "rule_def": {
            "logic": "and",
            "name": "Near-ATH Consolidation",
            "description": "Price within 3% of 52-week high with quiet volume and RSI below 65 — tight coil before breakout.",
            "source_text": "Find names within 3% of their 52-week high on quiet volume with RSI under 65.",
            "conditions": [
                {"field": "close_to_ath_pct", "op": "<=", "value": 3.0},
                {"field": "volume_ratio", "op": "<", "value": 1.2},
                {"field": "rsi_14", "op": "<", "value": 65},
            ],
        },
    },
    "oversold_dip": {
        "name": "Oversold Dip",
        "priority": "high",
        "weight": 1.5,  # Contrarian/Reversal: mean reversion with trend support
        "rule_summary": "Long-term trend intact (above 50DMA) but RSI dipped into oversold territory — dip-buy setup",
        "rule_def": {
            "logic": "and",
            "name": "Oversold Dip in Uptrend",
            "description": "Price held above 50DMA (trend intact) while RSI dipped below 40 (short-term oversold).",
            "source_text": "Find names above the 50DMA with RSI below 40 — classic dip-buy into trend support.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "sma_50"},
                {"field": "rsi_14", "op": "<", "value": 40},
            ],
        },
    },
    "pre_earnings_momentum": {
        "name": "Pre-Earnings Momentum",
        "priority": "high",
        "weight": 1.5,  # Tactical: time-bound event signal, actionable within 7-day window
        "rule_summary": "Earnings within 7 days, price above 20DMA, RSI above 55 — pre-earnings run setup",
        "rule_def": {
            "logic": "and",
            "name": "Pre-Earnings Momentum",
            "description": "Upcoming earnings (≤7 days) with price above 20DMA and RSI above 55.",
            "source_text": "Find names heading into earnings on positive price and momentum — pre-earnings run plays.",
            "conditions": [
                {"field": "earnings_in_days", "op": "<=", "value": 7},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": ">=", "value": 55},
            ],
        },
    },
    "high_vol_day": {
        "name": "High-Volume Day",
        "priority": "high",
        "weight": 2.0,  # Primary Momentum: institutional accumulation confirmation
        "rule_summary": "Volume at least 2x average with RSI above 55 and price above 20DMA — institutional buying",
        "rule_def": {
            "logic": "and",
            "name": "High-Volume Momentum Day",
            "description": "Big volume day (≥2× avg) with momentum confirming direction — institutional accumulation signal.",
            "source_text": "Flag names with volume at least 2x average, RSI above 55, and price above the 20DMA.",
            "conditions": [
                {"field": "volume_ratio", "op": ">=", "value": 2.0},
                {"field": "rsi_14", "op": ">=", "value": 55},
                {"field": "close", "op": ">", "value_from": "sma_20"},
            ],
        },
    },
    "strong_trending_day": {
        "name": "Strong Trending Day",
        "priority": "high",
        "weight": 2.0,  # Primary Momentum: confirmed price action breakout
        "rule_summary": "Single-day gain of 3%+ with volume confirmation inside an uptrend — momentum breakout",
        "rule_def": {
            "logic": "and",
            "name": "Strong Trending Day",
            "description": "Strong single-day gain (≥3%) on volume at least 1.5x average while above the 20DMA — momentum breakout.",
            "source_text": "Flag names with a 3%+ day on volume at least 1.5x average while above the 20DMA.",
            "conditions": [
                {"field": "change_percent", "op": ">=", "value": 3.0},
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "near_52w_support": {
        "name": "Near 52-Week Support",
        "priority": "high",
        "weight": 1.5,  # Structural: annual floor is a meaningful level — buyers historically step in
        "rule_summary": "Price within 5% of 52-week low with RSI cooling — potential support bounce",
        "rule_def": {
            "logic": "and",
            "name": "Near 52-Week Support",
            "description": "Price within 5% of the 52-week floor with RSI below 45 — testing major long-term support, potential reversal.",
            "source_text": "Find names within 5% of their 52-week low with RSI under 45 — buyers historically step in near the annual floor.",
            "conditions": [
                {"field": "close_to_support_pct", "op": "<=", "value": 5.0},
                {"field": "rsi_14", "op": "<", "value": 45},
            ],
        },
    },
    "pivot_s1_bounce": {
        "name": "Pivot S1 Bounce",
        "priority": "high",
        "weight": 1.0,  # Tactical/Minor: short-term support hold, needs other confirmation
        "rule_summary": "Price holding within 3% above S1 pivot support with RSI not stretched — classic intraday support hold",
        "rule_def": {
            "logic": "and",
            "name": "Pivot S1 Bounce",
            "description": "Price just above S1 pivot support (within 3%) with RSI below 50 — holding support after a test.",
            "source_text": "Find names where price is within 3% above S1 and RSI < 50 — pivot support holding, potential bounce entry.",
            "conditions": [
                {"field": "close_to_s1_pct", "op": ">=", "value": 0.0},
                {"field": "close_to_s1_pct", "op": "<=", "value": 3.0},
                {"field": "rsi_14", "op": "<", "value": 50},
            ],
        },
    },
    "pivot_r1_breakout": {
        "name": "Pivot R1 Breakout",
        "priority": "high",
        "weight": 1.5,  # Confirmation: level breakout with volume — resistance-to-support flip
        "rule_summary": "Price broke above R1 pivot resistance on above-average volume — resistance turned support",
        "rule_def": {
            "logic": "and",
            "name": "Pivot R1 Breakout",
            "description": "Price closed above R1 pivot resistance on volume at least 1.5x average — clean resistance breakout.",
            "source_text": "Flag names where price closed above R1 on elevated volume — pivot resistance broken, next target R2.",
            "conditions": [
                {"field": "close_to_r1_pct", "op": "<=", "value": 0.0},
                {"field": "volume_ratio", "op": ">=", "value": 1.5},
            ],
        },
    },
    "td_buy": {
        "name": "TD Buy Setup",
        "priority": "high",
        "weight": 1.5,  # Contrarian/Reversal: count-based exhaustion, context-dependent
        "rule_summary": "9 consecutive closes below close[i-4] — 神奇九转 exhaustion signal, potential reversal up",
        "rule_def": {
            "logic": "and",
            "name": "TD Sequential Buy Setup",
            "description": "Nine consecutive closes each below the close four bars prior — classic DeMark exhaustion signal indicating selling pressure may be spent.",
            "source_text": "Flag when 9 consecutive bars close below close[i-4] — TD Sequential buy setup (神奇九转买入).",
            "conditions": [
                {"field": "td_buy_setup", "op": ">=", "value": 9},
            ],
        },
    },
    "td_sell": {
        "name": "TD Sell Setup",
        "priority": "high",
        "weight": 1.5,  # Contrarian/Reversal: count-based exhaustion, context-dependent
        "rule_summary": "9 consecutive closes above close[i-4] — 神奇九转 exhaustion signal, potential reversal down",
        "rule_def": {
            "logic": "and",
            "name": "TD Sequential Sell Setup",
            "description": "Nine consecutive closes each above the close four bars prior — DeMark exhaustion signal indicating buying pressure may be spent.",
            "source_text": "Flag when 9 consecutive bars close above close[i-4] — TD Sequential sell setup (神奇九转卖出).",
            "conditions": [
                {"field": "td_sell_setup", "op": ">=", "value": 9},
            ],
        },
    },
}


def compute_rsi(series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2) if not rsi.empty else float("nan")


def fetch_market_data(tickers: List[str]) -> Dict[str, dict]:
    """Download 90 days of daily OHLCV data and compute technicals for each ticker."""
    import pandas as pd
    import yfinance as yf

    end = datetime.now()
    start = end - timedelta(days=365)

    logger.info("Downloading market data for %d tickers (%s to %s)",
                len(tickers), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    yf_tickers = [t.replace(".", "-") for t in tickers]
    ticker_map = {yf_sym: orig for yf_sym, orig in zip(yf_tickers, tickers)}

    raw = yf.download(
        yf_tickers,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    logger.info("yfinance download complete: %d rows, %d columns", len(raw), len(raw.columns))

    is_multi = isinstance(raw.columns, pd.MultiIndex)
    results: Dict[str, dict] = {}
    skipped_insufficient: list = []
    skipped_error: list = []

    for yf_sym, orig_ticker in ticker_map.items():
        try:
            if is_multi:
                close_s = raw[("Close", yf_sym)].dropna()
                open_s = raw[("Open", yf_sym)].dropna()
                high_s = raw[("High", yf_sym)].dropna()
                low_s = raw[("Low", yf_sym)].dropna()
                vol_s = raw[("Volume", yf_sym)].dropna()
            else:
                close_s = raw["Close"].dropna()
                open_s = raw["Open"].dropna()
                high_s = raw["High"].dropna()
                low_s = raw["Low"].dropna()
                vol_s = raw["Volume"].dropna()

            if len(close_s) < 21:
                skipped_insufficient.append(orig_ticker)
                continue

            close_today = float(close_s.iloc[-1])
            close_prev = float(close_s.iloc[-2])
            open_today = round(float(open_s.iloc[-1]), 2) if len(open_s) > 0 else round(close_today, 2)
            high_today = round(float(high_s.iloc[-1]), 2) if len(high_s) > 0 else round(close_today, 2)
            low_today = round(float(low_s.iloc[-1]), 2) if len(low_s) > 0 else round(close_today, 2)
            change_pct = round((close_today - close_prev) / close_prev * 100, 2)
            sma_20 = round(float(close_s.iloc[-20:].mean()), 2)
            sma_50 = round(float(close_s.iloc[-50:].mean()), 2) if len(close_s) >= 50 else sma_20
            # Previous day's SMAs — needed to detect crossover events (not just states)
            prev_sma_20 = round(float(close_s.iloc[-21:-1].mean()), 2)
            prev_sma_50 = round(float(close_s.iloc[-51:-1].mean()), 2) if len(close_s) >= 51 else prev_sma_20
            ema_20 = round(float(close_s.ewm(span=20, adjust=False).mean().iloc[-1]), 2)
            rsi = compute_rsi(close_s)
            avg_vol = float(vol_s.iloc[-20:].mean()) if len(vol_s) >= 20 else float(vol_s.mean())
            high_52w = round(float(close_s.iloc[-252:].max()), 2)
            low_52w = round(float(close_s.iloc[-252:].min()), 2)
            volume_today = float(vol_s.iloc[-1]) if len(vol_s) > 0 else 0.0
            volume_ratio = round(volume_today / avg_vol, 2) if avg_vol > 0 else 1.0
            close_to_ath_pct = round((high_52w - close_today) / high_52w * 100, 2) if high_52w > 0 else 0.0
            close_to_support_pct = round((close_today - low_52w) / low_52w * 100, 2) if low_52w > 0 else 0.0

            # Previous session OHLC (basis for daily pivot calculation)
            prev_high = float(high_s.iloc[-2]) if len(high_s) >= 2 else float(high_s.iloc[-1])
            prev_low = float(low_s.iloc[-2]) if len(low_s) >= 2 else float(low_s.iloc[-1])
            prev_open = round(float(open_s.iloc[-2]), 2) if len(open_s) >= 2 else open_today
            pivot = round((prev_high + prev_low + close_prev) / 3, 2)
            pivot_r1 = round(2 * pivot - prev_low, 2)
            pivot_r2 = round(pivot + (prev_high - prev_low), 2)
            pivot_s1 = round(2 * pivot - prev_high, 2)
            pivot_s2 = round(pivot - (prev_high - prev_low), 2)
            # % distance: positive = above S1/below R1, negative = below S1/above R1
            close_to_s1_pct = round((close_today - pivot_s1) / pivot_s1 * 100, 2) if pivot_s1 > 0 else 0.0
            close_to_r1_pct = round((pivot_r1 - close_today) / pivot_r1 * 100, 2) if pivot_r1 > 0 else 0.0

            # TD Sequential: count consecutive closes vs close[i-4]
            td_buy = 0
            td_sell = 0
            for i in range(4, len(close_s)):
                c, c4 = float(close_s.iloc[i]), float(close_s.iloc[i - 4])
                if c < c4:
                    td_buy += 1
                    td_sell = 0
                elif c > c4:
                    td_sell += 1
                    td_buy = 0
                else:
                    td_buy = 0
                    td_sell = 0

            # Long-term (200-day) levels for trend context and S/R
            sma_200 = round(float(close_s.iloc[-200:].mean()), 2) if len(close_s) >= 200 else sma_50
            high_200d = round(float(high_s.iloc[-200:].max()), 2) if len(high_s) >= 200 else high_52w
            low_200d = round(float(low_s.iloc[-200:].min()), 2) if len(low_s) >= 200 else low_52w
            # Close price exactly 200 sessions ago — "open" of the 200-day window
            open_200d = round(float(close_s.iloc[-200]), 2) if len(close_s) >= 200 else None
            # Standard pivot-point formula applied to the 200-day range
            lt_pivot = round((high_200d + low_200d + close_today) / 3, 2)
            lt_pivot_r1 = round(2 * lt_pivot - low_200d, 2)
            lt_pivot_r2 = round(lt_pivot + (high_200d - low_200d), 2)
            lt_pivot_s1 = round(2 * lt_pivot - high_200d, 2)
            lt_pivot_s2 = round(lt_pivot - (high_200d - low_200d), 2)
            # Max 200d S2 at zero so display doesn't show negative support levels
            lt_pivot_s2 = max(lt_pivot_s2, 0.0)

            results[orig_ticker] = {
                # Current session
                "open": open_today,
                "close": round(close_today, 2),
                "high": high_today,
                "low": low_today,
                "change_percent": change_pct,
                # Previous session (pivot basis)
                "prev_open": prev_open,
                "prev_close": round(close_prev, 2),
                "prev_high": round(prev_high, 2),
                "prev_low": round(prev_low, 2),
                # Moving averages
                "sma_20": sma_20,
                "sma_50": sma_50,
                "prev_sma_20": prev_sma_20,
                "prev_sma_50": prev_sma_50,
                "ema_20": ema_20,
                "rsi_14": rsi,
                # Volume
                "volume": volume_today,
                "avg_volume_20d": avg_vol,
                "volume_ratio": volume_ratio,
                # 52-week range
                "high_52w": high_52w,
                "low_52w": low_52w,
                "close_to_ath_pct": close_to_ath_pct,
                "close_to_support_pct": close_to_support_pct,
                # Daily pivot points
                "pivot_point": pivot,
                "pivot_r1": pivot_r1,
                "pivot_r2": pivot_r2,
                "pivot_s1": pivot_s1,
                "pivot_s2": pivot_s2,
                "close_to_s1_pct": close_to_s1_pct,
                "close_to_r1_pct": close_to_r1_pct,
                # TD Sequential
                "td_buy_setup": td_buy,
                "td_sell_setup": td_sell,
                # Long-term (200-day) levels
                "sma_200": sma_200,
                "high_200d": high_200d,
                "low_200d": low_200d,
                "open_200d": open_200d,
                "lt_pivot_r1": lt_pivot_r1,
                "lt_pivot_r2": lt_pivot_r2,
                "lt_pivot_s1": lt_pivot_s1,
                "lt_pivot_s2": lt_pivot_s2,
            }
        except Exception as exc:
            skipped_error.append(orig_ticker)
            logger.warning("Failed to compute metrics for %s: %s", orig_ticker, exc)

    if skipped_insufficient:
        logger.warning("Skipped %d tickers with <21 days of data: %s",
                       len(skipped_insufficient), ", ".join(skipped_insufficient))
    if skipped_error:
        logger.warning("Skipped %d tickers due to errors: %s",
                       len(skipped_error), ", ".join(skipped_error))
    logger.info("fetch_market_data complete: %d/%d tickers returned metrics",
                len(results), len(tickers))
    return results
