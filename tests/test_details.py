import importlib
import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload():
    """Reload details module so module-level _api_key_cache resets between tests."""
    import stock_analysis.details as m
    importlib.reload(m)
    return m


_SAMPLE_METRICS = {
    "company_name": "NVIDIA",
    "close": 872.45,
    "change_percent": 2.3,
    "volume_ratio": 2.11,
    "rsi_14": 68.4,
    "ema_20": 830.0,
    "sma_20": 825.0,
    "sma_50": 780.0,
    "high_52w": 872.45,
    "low_52w": 400.0,
    "pivot_r1": 900.0,
    "pivot_r2": 930.0,
    "pivot_s1": 840.0,
    "pivot_s2": 810.0,
}

_SAMPLE_RULE_CONFIGS = {
    "ath_breakout": {
        "name": "ATH Breakout",
        "priority": "high",
        "rule_def": {
            "description": "Price breaches 52-week high on elevated volume.",
        },
    },
    "high_vol_day": {
        "name": "High-Volume Momentum Day",
        "priority": "high",
        "rule_def": {
            "description": "Big volume day with momentum confirming direction.",
        },
    },
}

_SAMPLE_ANALYSIS = {
    "summary": "NVIDIA is surging on AI demand.",
    "rules": [
        {"name": "ATH Breakout", "priority": "High", "status": "triggered", "details": "Close $872.45 >= 52W high"}
    ],
    "priceTargets": {
        "resistance": [{"label": "R1 (Pivot)", "price": 900.0, "note": "First pivot"}],
        "support": [{"label": "S1 (Pivot)", "price": 840.0, "note": ""}],
        "entry": {"low": 840.0, "high": 860.0, "note": "Pullback to S1"},
        "stopLoss": {"price": 810.0, "note": "Below S2"},
    },
    "verdict": {
        "action": "Hold",
        "rationale": "ATH Breakout and High-Volume day confluence.",
        "strategy": "Hold above $840 S1; exit below $810.",
    },
}


def _make_mock_gemini(response_text: str):
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_genai = MagicMock()
    mock_genai.Client.return_value = mock_client
    mock_types = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    return mock_google, mock_genai, mock_types


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_returns_direct_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "direct-key-abc")
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload()
        assert m._get_api_key() == "direct-key-abc"

    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload()
        assert m._get_api_key() == ""

    def test_fetches_from_secrets_manager(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_SECRET_NAME", "stock-analysis/gemini-api-key")
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": "sm-key-xyz"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_sm
        m = _reload()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            key = m._get_api_key()
        assert key == "sm-key-xyz"

    def test_returns_empty_on_secrets_manager_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_SECRET_NAME", "stock-analysis/gemini-api-key")
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = Exception("access denied")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_sm
        m = _reload()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            key = m._get_api_key()
        assert key == ""


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_ticker_and_date(self):
        m = _reload()
        prompt = m._build_prompt("NVDA", "NVIDIA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "NVDA" in prompt
        assert "NVIDIA" in prompt
        assert "2026-04-26" in prompt

    def test_includes_close_price(self):
        m = _reload()
        prompt = m._build_prompt("NVDA", "NVIDIA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "872.45" in prompt

    def test_includes_rule_description(self):
        m = _reload()
        prompt = m._build_prompt("NVDA", "NVIDIA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "Price breaches 52-week high on elevated volume." in prompt

    def test_includes_earnings_when_present(self):
        m = _reload()
        metrics = {**_SAMPLE_METRICS, "earnings_date": "2026-05-07", "earnings_in_days": 11, "earnings_timing": "After Close"}
        prompt = m._build_prompt("NVDA", "NVIDIA", metrics, [], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "2026-05-07" in prompt
        assert "11 days away" in prompt

    def test_omits_earnings_when_absent(self):
        m = _reload()
        prompt = m._build_prompt("NVDA", "NVIDIA", _SAMPLE_METRICS, [], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "Earnings:" not in prompt

    def test_unknown_rule_name_included_without_description(self):
        m = _reload()
        prompt = m._build_prompt("NVDA", "NVIDIA", _SAMPLE_METRICS, ["Unknown Rule"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert "Unknown Rule" in prompt

    def test_handles_zero_metrics_safely(self):
        m = _reload()
        prompt = m._build_prompt("X", "X Corp", {}, [], {}, "2026-04-26")
        assert "X" in prompt


# ---------------------------------------------------------------------------
# generate_ticker_analysis
# ---------------------------------------------------------------------------

class TestGenerateTickerAnalysis:
    def test_returns_parsed_dict_on_success(self, monkeypatch):
        mock_google, mock_genai, mock_types = _make_mock_gemini(json.dumps(_SAMPLE_ANALYSIS))
        m = _reload()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_ticker_analysis("NVDA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert result is not None
        assert result["summary"] == "NVIDIA is surging on AI demand."
        assert result["verdict"]["action"] == "Hold"

    def test_returns_none_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload()
        result = m.generate_ticker_analysis("NVDA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert result is None

    def test_returns_none_on_gemini_exception(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("quota exceeded")
        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_types = MagicMock()
        mock_google = MagicMock()
        mock_google.genai = mock_genai
        m = _reload()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_ticker_analysis("NVDA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert result is None

    def test_returns_none_on_invalid_json(self, monkeypatch):
        mock_google, mock_genai, mock_types = _make_mock_gemini("not valid json at all")
        m = _reload()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_ticker_analysis("NVDA", _SAMPLE_METRICS, ["ATH Breakout"], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert result is None

    def test_uses_company_name_from_metrics(self, monkeypatch):
        captured_prompts = []
        mock_response = MagicMock()
        mock_response.text = json.dumps(_SAMPLE_ANALYSIS)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = lambda **kwargs: (captured_prompts.append(kwargs.get("contents", "")), mock_response)[1]
        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_types = MagicMock()
        mock_google = MagicMock()
        mock_google.genai = mock_genai
        m = _reload()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            m.generate_ticker_analysis("NVDA", _SAMPLE_METRICS, [], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert any("NVIDIA" in p for p in captured_prompts)

    def test_falls_back_to_ticker_as_company_name(self, monkeypatch):
        mock_google, mock_genai, mock_types = _make_mock_gemini(json.dumps(_SAMPLE_ANALYSIS))
        m = _reload()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_ticker_analysis("NVDA", {}, [], _SAMPLE_RULE_CONFIGS, "2026-04-26")
        assert result is not None


# ---------------------------------------------------------------------------
# Integration test — requires GEMINI_API_KEY in environment
# ---------------------------------------------------------------------------

_AMZN_METRICS = {
    "company_name": "Amazon.com",
    "close": 185.30,
    "change_percent": 1.8,
    "volume_ratio": 1.45,
    "rsi_14": 61.2,
    "ema_20": 178.50,
    "sma_20": 177.80,
    "sma_50": 168.40,
    "high_52w": 191.70,
    "low_52w": 118.35,
    "pivot_r1": 192.00,
    "pivot_r2": 198.50,
    "pivot_s1": 179.00,
    "pivot_s2": 172.50,
    "earnings_date": "2026-05-01",
    "earnings_in_days": 5,
    "earnings_timing": "After Close",
}

_AMZN_RULE_CONFIGS = {
    "ma_stack": {
        "name": "Bullish MA Stack",
        "priority": "high",
        "rule_def": {"description": "Close > EMA-20 > SMA-50 — all three in bullish alignment."},
    },
    "pre_earnings": {
        "name": "Pre-Earnings Momentum",
        "priority": "high",
        "rule_def": {"description": "Stock trending higher within 1–7 days of earnings report."},
    },
}


@pytest.mark.skipif(
    not __import__("os").environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set — skipping live Gemini integration test",
)
def test_integration_amzn_analysis_shape():
    """Live call to Gemini: verify AMZN analysis returns the expected JSON contract."""
    m = _reload()
    result = m.generate_ticker_analysis(
        ticker="AMZN",
        metrics=_AMZN_METRICS,
        rule_names=["Bullish MA Stack", "Pre-Earnings Momentum"],
        rule_configs=_AMZN_RULE_CONFIGS,
        trade_date="2026-04-26",
    )

    assert result is not None, "Gemini returned None — check API key and quota"

    # Top-level keys
    assert "summary" in result
    assert "rules" in result
    assert "priceTargets" in result
    assert "verdict" in result

    # Summary is a non-empty string
    assert isinstance(result["summary"], str) and len(result["summary"]) > 20

    # Each rule entry has required fields
    for rule in result["rules"]:
        assert "name" in rule
        assert "status" in rule
        assert "details" in rule

    # priceTargets structure
    pt = result["priceTargets"]
    assert isinstance(pt.get("resistance"), list) and len(pt["resistance"]) > 0
    assert isinstance(pt.get("support"), list) and len(pt["support"]) > 0
    entry = pt.get("entry", {})
    assert isinstance(entry.get("low"), (int, float))
    assert isinstance(entry.get("high"), (int, float))
    stop = pt.get("stopLoss", {})
    assert isinstance(stop.get("price"), (int, float))

    # Verdict has action from allowed set
    verdict = result["verdict"]
    assert verdict.get("action") in {
        "Strong Buy", "Tactical Buy", "Hold", "Profit-Taking", "Stop-Loss"
    }
    assert isinstance(verdict.get("rationale"), str) and len(verdict["rationale"]) > 10
    assert isinstance(verdict.get("strategy"), str) and len(verdict["strategy"]) > 10
