"""
Per-ticker AI analysis using Google Gemini.

Generates a structured trading brief (summary, rule scanning status, price
targets, verdict) for a given ticker based on its current market metrics and
the rules it matched.  Returns a dict on success, None on any failure so the
aggregator can skip gracefully without crashing.

API key resolution: same priority order as news.py —
  1. GEMINI_API_KEY env var (local dev / CI)
  2. GEMINI_SECRET_NAME env var → AWS Secrets Manager (production Lambda)
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_api_key_cache: str = ""


def _get_api_key() -> str:
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache

    direct = os.environ.get("GEMINI_API_KEY", "")
    if direct:
        _api_key_cache = direct
        return _api_key_cache

    secret_name = os.environ.get("GEMINI_SECRET_NAME", "")
    if not secret_name:
        logger.warning("Neither GEMINI_API_KEY nor GEMINI_SECRET_NAME is set")
        return ""

    try:
        import boto3
        sm = boto3.client("secretsmanager")
        resp = sm.get_secret_value(SecretId=secret_name)
        _api_key_cache = resp["SecretString"]
        logger.info("Loaded Gemini API key from Secrets Manager (%s)", secret_name)
        return _api_key_cache
    except Exception as exc:
        logger.error("Failed to fetch API key from Secrets Manager: %s", exc)
        return ""


def _build_prompt(
    ticker: str,
    company_name: str,
    metrics: Dict[str, Any],
    rule_names: List[str],
    rule_configs: Dict[str, Any],
    trade_date: str,
) -> str:
    close = metrics.get("close", 0) or 0
    change_pct = metrics.get("change_percent", 0) or 0
    volume_ratio = metrics.get("volume_ratio", 0) or 0
    rsi = metrics.get("rsi_14", 0) or 0
    ema_20 = metrics.get("ema_20", 0) or 0
    sma_20 = metrics.get("sma_20", 0) or 0
    sma_50 = metrics.get("sma_50", 0) or 0
    high_52w = metrics.get("high_52w", 0) or 0
    low_52w = metrics.get("low_52w", 0) or 0
    pivot_r1 = metrics.get("pivot_r1", 0) or 0
    pivot_r2 = metrics.get("pivot_r2", 0) or 0
    pivot_s1 = metrics.get("pivot_s1", 0) or 0
    pivot_s2 = metrics.get("pivot_s2", 0) or 0

    earnings_line = ""
    earnings_in_days = metrics.get("earnings_in_days")
    earnings_date = metrics.get("earnings_date")
    if earnings_date and earnings_in_days is not None:
        timing = metrics.get("earnings_timing", "TBD")
        earnings_line = f"\n- Earnings: {earnings_date} ({earnings_in_days} days away, {timing})"

    rule_lines = []
    for name in rule_names:
        cfg = next((v for v in rule_configs.values() if v.get("name") == name), None)
        if cfg:
            desc = cfg.get("rule_def", {}).get("description", "")
            rule_lines.append(f"- {name}: {desc}")
        else:
            rule_lines.append(f"- {name}")
    rules_block = "\n".join(rule_lines)

    return f"""You are a Professional Quantitative Analyst. Analyze {ticker} ({company_name}) based on the following live market data and provide a structured trading brief for the next trading session.

TICKER: {ticker} ({company_name})
TRADE DATE: {trade_date}

MARKET METRICS:
- Close Price: ${close:.2f}
- Daily Change: {change_pct:+.1f}%
- Volume Ratio (vs 20d avg): {volume_ratio:.2f}x
- RSI(14): {rsi:.1f}
- EMA-20: ${ema_20:.2f}
- SMA-20: ${sma_20:.2f}
- SMA-50: ${sma_50:.2f}
- 52-Week High: ${high_52w:.2f}
- 52-Week Low: ${low_52w:.2f}
- Pivot R1: ${pivot_r1:.2f}
- Pivot R2: ${pivot_r2:.2f}
- Pivot S1: ${pivot_s1:.2f}
- Pivot S2: ${pivot_s2:.2f}{earnings_line}

TRIGGERED RULES ({len(rule_names)} matched):
{rules_block}

Return a JSON object with exactly this structure (use the real metric values provided above):
{{
  "summary": "2-3 sentences describing what is driving this stock, mentioning sector context, specific catalysts if known, and which metrics stand out",
  "rules": [
    {{
      "name": "Rule name matching one of the triggered rules above",
      "priority": "High",
      "status": "triggered or warning",
      "details": "Specific numbers that triggered this rule (e.g. 'Surged +13.9% on volume ratio 2.11x avg')"
    }}
  ],
  "priceTargets": {{
    "resistance": [
      {{"label": "R1 (Pivot)", "price": {pivot_r1:.2f}, "note": "First pivot resistance"}},
      {{"label": "R2 (Pivot)", "price": {pivot_r2:.2f}, "note": "Second pivot resistance — extended target"}}
    ],
    "support": [
      {{"label": "S1 (Pivot)", "price": {pivot_s1:.2f}, "note": "First pivot support"}},
      {{"label": "EMA-20", "price": {ema_20:.2f}, "note": "Short-term trend anchor"}},
      {{"label": "SMA-50", "price": {sma_50:.2f}, "note": "Medium-term trend floor"}}
    ],
    "entry": {{
      "low": 0.0,
      "high": 0.0,
      "note": "Describe the ideal entry zone and why"
    }},
    "stopLoss": {{
      "price": 0.0,
      "note": "Stop-loss level rationale — which support it sits below"
    }}
  }},
  "verdict": {{
    "action": "One of: Strong Buy / Tactical Buy / Hold / Profit-Taking / Stop-Loss",
    "rationale": "Which rules are confluencing and why that justifies the action",
    "strategy": "Specific next-session instructions with exact price levels from the data above"
  }}
}}

Important: populate entry.low, entry.high, and stopLoss.price with real numbers calculated from the support/resistance levels and the stock's recent volatility range."""


def generate_ticker_analysis(
    ticker: str,
    metrics: Dict[str, Any],
    rule_names: List[str],
    rule_configs: Dict[str, Any],
    trade_date: str,
) -> Optional[Dict[str, Any]]:
    """Generate a structured AI trading brief for one ticker.  Returns None on any failure."""
    api_key = _get_api_key()
    if not api_key:
        return None

    company_name = metrics.get("company_name") or ticker
    prompt = _build_prompt(ticker, company_name, metrics, rule_names, rule_configs, trade_date)

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2000,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        result = json.loads(response.text)
        logger.info("Generated ticker analysis for %s (%d chars)", ticker, len(response.text))
        return result
    except Exception as exc:
        logger.error("Ticker analysis failed for %s: %s", ticker, exc)
        return None
