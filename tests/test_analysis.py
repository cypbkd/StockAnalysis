import json
import sys
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ANALYSIS = {
    "summary": "NVIDIA is surging.",
    "rules": [{"name": "ATH Breakout", "priority": "High", "status": "triggered", "details": "Close >= 52W high"}],
    "priceTargets": {
        "resistance": [{"label": "R1", "price": 900.0, "note": ""}],
        "support": [{"label": "S1", "price": 840.0, "note": ""}],
        "entry": {"low": 840.0, "high": 860.0, "note": ""},
        "stopLoss": {"price": 810.0, "note": ""},
    },
    "verdict": {"action": "Hold", "rationale": "Confluence.", "strategy": "Wait for S1."},
}

_SAMPLE_REPORT = {
    "reportDate": "2026-04-26",
    "stockSignals": [
        {
            "symbol": "NVDA",
            "companyName": "NVIDIA",
            "lastPrice": 872.45,
            "changePercent": 2.3,
            "ruleNames": ["ATH Breakout"],
            "status": "high priority",
            "technicalData": {
                "volumeRatio": 2.11,
                "rsi14": 68.4,
                "ema20": 830.0,
                "sma20": 825.0,
                "sma50": 780.0,
                "high52w": 872.45,
                "low52w": 400.0,
                "pivotR1": 900.0,
                "pivotR2": 930.0,
                "pivotS1": 840.0,
                "pivotS2": 810.0,
            },
        }
    ],
}


def _make_s3_client(report_json=None, cached_analysis=None):
    """Build a mock S3 client with NoSuchKey defined as a real exception type."""
    NoSuchKey = type("NoSuchKey", (Exception,), {})

    s3 = MagicMock()
    s3.exceptions.NoSuchKey = NoSuchKey

    def get_object_side_effect(Bucket, Key):
        if cached_analysis is not None and Key.startswith("analyses/"):
            body = MagicMock()
            body.read.return_value = json.dumps(cached_analysis).encode()
            return {"Body": body}
        if report_json is not None and Key.startswith("reports/"):
            body = MagicMock()
            body.read.return_value = json.dumps(report_json).encode()
            return {"Body": body}
        raise NoSuchKey("not found")

    s3.get_object.side_effect = get_object_side_effect
    return s3


def _mock_boto3(s3_client):
    mock = MagicMock()
    mock.client.return_value = s3_client
    return mock


def _make_event(ticker="NVDA", date="2026-04-26", method="GET"):
    return {
        "requestContext": {"http": {"method": method}},
        "queryStringParameters": {"ticker": ticker, "date": date},
    }


# ---------------------------------------------------------------------------
# handler
# ---------------------------------------------------------------------------

class TestAnalysisHandler:
    def test_options_preflight_returns_200(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        response = m.handler(_make_event(method="OPTIONS"), None)
        assert response["statusCode"] == 200

    def test_missing_ticker_returns_400(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        event = {"requestContext": {"http": {"method": "GET"}}, "queryStringParameters": {}}
        response = m.handler(event, None)
        assert response["statusCode"] == 400
        assert "ticker" in json.loads(response["body"])["error"]

    def test_missing_cache_bucket_returns_500(self, monkeypatch):
        monkeypatch.delenv("CACHE_BUCKET", raising=False)
        import stock_analysis.handlers.analysis as m
        response = m.handler(_make_event(), None)
        assert response["statusCode"] == 500

    def test_returns_cached_analysis_without_calling_gemini(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(cached_analysis=_SAMPLE_ANALYSIS)
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}), \
             patch.object(m, "generate_ticker_analysis") as mock_gen:
            response = m.handler(_make_event(), None)
        assert response["statusCode"] == 200
        mock_gen.assert_not_called()
        body = json.loads(response["body"])
        assert body["summary"] == "NVIDIA is surging."

    def test_generates_analysis_on_cache_miss_and_caches_result(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}), \
             patch.object(m, "generate_ticker_analysis", return_value=_SAMPLE_ANALYSIS):
            response = m.handler(_make_event(), None)
        assert response["statusCode"] == 200
        put_calls = mock_s3.put_object.call_args_list
        assert any("analyses/" in str(c) for c in put_calls)

    def test_returns_404_when_signal_not_in_report(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(report_json={"stockSignals": []})
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}):
            response = m.handler(_make_event(ticker="UNKNOWN"), None)
        assert response["statusCode"] == 404

    def test_returns_503_when_gemini_returns_none(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}), \
             patch.object(m, "generate_ticker_analysis", return_value=None):
            response = m.handler(_make_event(), None)
        assert response["statusCode"] == 503

    def test_cors_header_not_in_response(self, monkeypatch):
        # CORS is handled by the Lambda Function URL config, not the handler.
        # Having it in both places produces duplicate headers that browsers reject.
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}), \
             patch.object(m, "generate_ticker_analysis", return_value=_SAMPLE_ANALYSIS):
            response = m.handler(_make_event(), None)
        assert "Access-Control-Allow-Origin" not in response["headers"]

    def test_ticker_is_uppercased(self, monkeypatch):
        monkeypatch.setenv("CACHE_BUCKET", "test-bucket")
        import stock_analysis.handlers.analysis as m
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        with patch.dict(sys.modules, {"boto3": _mock_boto3(mock_s3)}), \
             patch.object(m, "generate_ticker_analysis", return_value=_SAMPLE_ANALYSIS) as mock_gen:
            m.handler(_make_event(ticker="nvda"), None)
        mock_gen.assert_called_once()
        first_arg = mock_gen.call_args[1].get("ticker") or mock_gen.call_args[0][0]
        assert first_arg == "NVDA"


# ---------------------------------------------------------------------------
# _find_signal_data
# ---------------------------------------------------------------------------

class TestFindSignalData:
    def _module(self):
        import stock_analysis.handlers.analysis as m
        return m

    def test_returns_metrics_and_rule_names_for_known_ticker(self):
        m = self._module()
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        metrics, rule_names = m._find_signal_data(mock_s3, "bucket", "2026-04-26", "NVDA")
        assert metrics is not None
        assert metrics["close"] == 872.45
        assert metrics["volume_ratio"] == 2.11
        assert metrics["rsi_14"] == 68.4
        assert rule_names == ["ATH Breakout"]

    def test_returns_none_for_unknown_ticker(self):
        m = self._module()
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        metrics, rule_names = m._find_signal_data(mock_s3, "bucket", "2026-04-26", "UNKNOWN")
        assert metrics is None
        assert rule_names == []

    def test_maps_company_name_from_signal(self):
        m = self._module()
        mock_s3 = _make_s3_client(report_json=_SAMPLE_REPORT)
        metrics, _ = m._find_signal_data(mock_s3, "bucket", "2026-04-26", "NVDA")
        assert metrics["company_name"] == "NVIDIA"
