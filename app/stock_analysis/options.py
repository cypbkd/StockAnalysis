"""
Real options chain analysis using yfinance.

Fetches live option chains for every matched ticker (not a fixed universe),
computes a composite score, and marks the top ideas as highlighted.

Composite score = options_quality_score (60%) + screening_strength (40%)
  - options_quality: IV sweet-spot, OI/liquidity, RSI alignment, price vs SMA
  - screening_strength: how many of the 14 rules the ticker matched
"""
import logging
import math
from dataclasses import replace
from datetime import datetime
from typing import List, Optional, Tuple

from stock_analysis.screening import OptionIdea

logger = logging.getLogger(__name__)

_MAX_RULES = 14         # normalisation denominator for match_count
_MIN_OI = 50            # contracts — minimum open interest for a usable strike
_TARGET_DTE = 21        # prefer expiration closest to 21 days out
_MIN_DTE = 7            # never use contracts expiring in less than a week
_TOP_N_HIGHLIGHT = 3    # how many ideas get highlighted=True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_expiration(expirations: tuple, target_dte: int = _TARGET_DTE) -> Optional[str]:
    today = datetime.now().date()
    best: Optional[str] = None
    best_diff = float("inf")
    for exp in expirations:
        try:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
            if dte < _MIN_DTE:
                continue
            diff = abs(dte - target_dte)
            if diff < best_diff:
                best_diff = diff
                best = exp
        except ValueError:
            continue
    return best


def _nearest_strike(df, target_price: float) -> Optional[float]:
    if df.empty:
        return None
    diffs = (df["strike"] - target_price).abs()
    return float(df.loc[diffs.idxmin(), "strike"])


def _safe_float(val, default: float = 0.0) -> float:
    try:
        f = float(val)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    try:
        f = float(val)
        return default if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return default


def _options_quality_score(iv_pct: float, oi: int, rsi: float, is_bullish: bool,
                            close: float, sma_20: float, pct_otm: float) -> int:
    """
    0-100 score based purely on options-chain quality metrics.

    IV sweet spot (25-65%): full 25 pts
    OI depth (log-scale):   25 pts
    RSI alignment:          20 pts
    Price vs SMA-20:        20 pts
    OTM cushion (bullish):  10 pts
    """
    score = 0

    # IV: sweet spot 25-65%
    if 25 <= iv_pct <= 65:
        score += 25
    elif 15 <= iv_pct < 25 or 65 < iv_pct <= 85:
        score += 12
    else:
        score += 5  # very low IV or very high IV — less ideal

    # OI: log-scale, capped at 25
    oi_pts = min(25, round(math.log10(max(oi, 1)) / math.log10(5000) * 25))
    score += max(0, oi_pts)

    # RSI alignment
    if is_bullish:
        if 40 <= rsi <= 65:
            score += 20
        elif 35 <= rsi < 40 or 65 < rsi <= 72:
            score += 10
    else:
        if rsi >= 65:
            score += 20
        elif rsi >= 55:
            score += 10

    # Price vs SMA-20
    if is_bullish and close > sma_20 > 0:
        score += 20
    elif not is_bullish and 0 < close < sma_20:
        score += 20
    elif sma_20 > 0:
        score += 5  # partial credit — some stocks gap above/below

    # OTM cushion (only relevant for bullish cash-secured puts)
    if is_bullish and pct_otm >= 4:
        score += 10

    return min(100, score)


def _composite_score(options_score: int, match_count: int) -> float:
    """Blend options quality (60%) with screening strength (40%)."""
    screening_pts = min(match_count, _MAX_RULES) / _MAX_RULES * 100
    return options_score * 0.6 + screening_pts * 0.4


# ---------------------------------------------------------------------------
# Per-ticker strategy builders
# ---------------------------------------------------------------------------

def _analyze_bullish(symbol: str, puts, close: float, metrics: dict, exp: str,
                     match_count: int) -> Optional[Tuple[OptionIdea, float]]:
    """
    Sell a cash-secured put ~5% OTM.
    Returns (OptionIdea, composite_score) or None.
    """
    target = close * 0.95
    put_strike = _nearest_strike(puts, target)
    if put_strike is None:
        return None

    row = puts[puts["strike"] == put_strike]
    if row.empty:
        return None
    row = row.iloc[0]

    bid = _safe_float(row.get("bid"))
    ask = _safe_float(row.get("ask"))
    mid = (bid + ask) / 2 if ask > 0 else bid
    iv = _safe_float(row.get("impliedVolatility")) * 100
    oi = _safe_int(row.get("openInterest"))
    vol = _safe_int(row.get("volume"))

    if mid < 0.05 or oi < _MIN_OI:
        # Fall back to ATM
        put_strike = _nearest_strike(puts, close)
        if put_strike is None:
            return None
        row = puts[puts["strike"] == put_strike]
        if row.empty:
            return None
        row = row.iloc[0]
        bid = _safe_float(row.get("bid"))
        ask = _safe_float(row.get("ask"))
        mid = (bid + ask) / 2 if ask > 0 else bid
        iv = _safe_float(row.get("impliedVolatility")) * 100
        oi = _safe_int(row.get("openInterest"))
        vol = _safe_int(row.get("volume"))

    if mid < 0.01:
        return None

    rsi = _safe_float(metrics.get("rsi_14"))
    chg = _safe_float(metrics.get("change_percent"))
    sma_20 = _safe_float(metrics.get("sma_20"))
    breakeven = put_strike - mid
    pct_otm = (close - put_strike) / close * 100

    opt_score = _options_quality_score(iv, oi, rsi, True, close, sma_20, pct_otm)
    comp = _composite_score(opt_score, match_count)

    idea = OptionIdea(
        symbol=symbol,
        strategy=f"Cash-secured put — sell ${put_strike:.0f} put",
        expiration=exp,
        score=round(opt_score, 1),
        reason=(
            f"Sell ${put_strike:.0f} put exp {exp} | "
            f"Mid ${mid:.2f}, IV {iv:.0f}%, OI {oi:,}, Vol {vol:,} | "
            f"Breakeven ${breakeven:.2f} ({pct_otm:.1f}% OTM) | "
            f"Stock ${close:.2f}, RSI {rsi:.0f}, day {chg:+.1f}%, "
            f"rules matched {match_count}"
        ),
        highlighted=False,
    )
    return idea, comp


def _analyze_bearish(symbol: str, puts, close: float, metrics: dict, exp: str,
                     match_count: int) -> Optional[Tuple[OptionIdea, float]]:
    """
    Bear put spread: buy ATM put, sell 5% OTM put.
    Returns (OptionIdea, composite_score) or None.
    """
    buy_strike = _nearest_strike(puts, close)
    sell_strike = _nearest_strike(puts, close * 0.95)

    if buy_strike is None or sell_strike is None or buy_strike == sell_strike:
        return None

    buy_row = puts[puts["strike"] == buy_strike]
    sell_row = puts[puts["strike"] == sell_strike]
    if buy_row.empty or sell_row.empty:
        return None

    buy_ask = _safe_float(buy_row.iloc[0].get("ask"))
    sell_bid = _safe_float(sell_row.iloc[0].get("bid"))
    net_debit = buy_ask - sell_bid
    iv = _safe_float(buy_row.iloc[0].get("impliedVolatility")) * 100
    oi = _safe_int(buy_row.iloc[0].get("openInterest"))
    vol = _safe_int(buy_row.iloc[0].get("volume"))
    max_profit = (buy_strike - sell_strike) - net_debit

    if net_debit <= 0.01 or oi < _MIN_OI:
        return None

    rsi = _safe_float(metrics.get("rsi_14"))
    chg = _safe_float(metrics.get("change_percent"))
    sma_20 = _safe_float(metrics.get("sma_20"))

    opt_score = _options_quality_score(iv, oi, rsi, False, close, sma_20, 0.0)
    comp = _composite_score(opt_score, match_count)

    idea = OptionIdea(
        symbol=symbol,
        strategy=f"Bear put spread — ${buy_strike:.0f}/${sell_strike:.0f}",
        expiration=exp,
        score=round(opt_score, 1),
        reason=(
            f"Buy ${buy_strike:.0f} / sell ${sell_strike:.0f} put exp {exp} | "
            f"Net debit ~${net_debit:.2f}, max profit ~${max_profit:.2f} | "
            f"IV {iv:.0f}%, OI {oi:,}, Vol {vol:,} | "
            f"Stock ${close:.2f}, RSI {rsi:.0f}, day {chg:+.1f}%, "
            f"rules matched {match_count}"
        ),
        highlighted=False,
    )
    return idea, comp


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_options_ideas(
    matched_results: list,
    max_candidates: int = 40,
    max_ideas: int = 10,
) -> List[OptionIdea]:
    """
    Fetch real options chains for every matched ticker and return concrete
    OptionIdea objects sorted by composite score, with the top 3 flagged
    as highlighted.

    ``matched_results`` is already sorted by match_count desc from the
    aggregator, so we just take the first ``max_candidates`` entries to
    cap yfinance API calls.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed; skipping options chain analysis")
        return []

    candidates = matched_results[:max_candidates]
    raw: List[Tuple[OptionIdea, float]] = []   # (idea, composite_score)
    seen: set = set()

    for item in candidates:
        symbol = item["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)

        metrics = item.get("metrics", {})
        close = _safe_float(metrics.get("close", 0))
        match_count = item.get("match_count", 1)
        if close <= 0:
            continue

        chg = _safe_float(metrics.get("change_percent", 0))
        is_bullish = chg >= 0

        try:
            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                logger.debug("%s: no options expirations", symbol)
                continue

            exp = _pick_expiration(expirations)
            if exp is None:
                logger.debug("%s: no suitable expiration (min %d DTE)", symbol, _MIN_DTE)
                continue

            chain = ticker.option_chain(exp)
            puts = chain.puts

            if is_bullish:
                result = _analyze_bullish(symbol, puts, close, metrics, exp, match_count)
            else:
                result = _analyze_bearish(symbol, puts, close, metrics, exp, match_count)

            if result is not None:
                raw.append(result)
                logger.info("%s: %s (composite=%.1f)", symbol, result[0].strategy, result[1])
            else:
                logger.debug("%s: no viable option idea (close=%.2f)", symbol, close)

        except Exception as exc:
            logger.warning("%s: options chain fetch failed: %s", symbol, exc)
            continue

    if not raw:
        return []

    # Sort by composite score descending
    raw.sort(key=lambda x: -x[1])

    # Mark top N as highlighted, return up to max_ideas
    output: List[OptionIdea] = []
    for i, (idea, _comp) in enumerate(raw[:max_ideas]):
        output.append(replace(idea, highlighted=(i < _TOP_N_HIGHLIGHT)))

    logger.info(
        "build_options_ideas: %d ideas total, %d highlighted",
        len(output),
        sum(1 for idea in output if idea.highlighted),
    )
    return output
