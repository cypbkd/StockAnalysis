import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_news():
    """Reload news module so module-level _api_key_cache is reset between tests."""
    import importlib
    import stock_analysis.news as m
    importlib.reload(m)
    return m


# ---------------------------------------------------------------------------
# _get_api_key
# ---------------------------------------------------------------------------

class TestGetApiKey:
    def test_returns_direct_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "direct-key-123")
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload_news()
        assert m._get_api_key() == "direct-key-123"

    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload_news()
        assert m._get_api_key() == ""

    def test_fetches_from_secrets_manager(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_SECRET_NAME", "stock-analysis/gemini-api-key")
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": "sm-key-456"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_sm
        m = _reload_news()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            key = m._get_api_key()
        assert key == "sm-key-456"
        mock_sm.get_secret_value.assert_called_once_with(
            SecretId="stock-analysis/gemini-api-key"
        )

    def test_returns_empty_on_secrets_manager_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_SECRET_NAME", "stock-analysis/gemini-api-key")
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = Exception("access denied")
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_sm
        m = _reload_news()
        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            key = m._get_api_key()
        assert key == ""


# ---------------------------------------------------------------------------
# generate_news_summary
# ---------------------------------------------------------------------------

class TestGenerateNewsSummary:
    def _make_mock_modules(self, text: str):
        """Return (mock_google_genai, mock_google_genai_types) for patching sys.modules."""
        mock_response = MagicMock()
        mock_response.text = text
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_types = MagicMock()
        mock_google = MagicMock()
        mock_google.genai = mock_genai
        return mock_google, mock_genai, mock_types

    def test_returns_summary_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        mock_google, mock_genai, mock_types = self._make_mock_modules("  Markets rallied on AI optimism.  ")
        m = _reload_news()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.object(m, "fetch_ticker_headlines", return_value=["NVDA beats earnings"]), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_news_summary(["NVDA"], "2026-04-25")
        assert result == "Markets rallied on AI optimism."

    def test_returns_empty_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_SECRET_NAME", raising=False)
        m = _reload_news()
        result = m.generate_news_summary(["NVDA"], "2026-04-25")
        assert result == ""

    def test_returns_empty_when_no_symbols(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        m = _reload_news()
        with patch.object(m, "_get_api_key", return_value="test-key"):
            result = m.generate_news_summary([], "2026-04-25")
        assert result == ""

    def test_returns_empty_when_no_headlines(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        m = _reload_news()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.object(m, "fetch_ticker_headlines", return_value=[]):
            result = m.generate_news_summary(["NVDA", "AAPL"], "2026-04-25")
        assert result == ""

    def test_caps_symbols_at_max_tickers(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_google, mock_genai, mock_types = self._make_mock_modules("Summary text.")
        m = _reload_news()
        fetch_calls = []

        def fake_fetch(symbol, max_items=3):
            fetch_calls.append(symbol)
            return [f"{symbol} headline"]

        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.object(m, "fetch_ticker_headlines", side_effect=fake_fetch), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            m.generate_news_summary(
                ["A", "B", "C", "D", "E", "F", "G", "H", "I"], "2026-04-25", max_tickers=3
            )
        assert fetch_calls == ["A", "B", "C"]

    def test_returns_empty_on_gemini_exception(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("quota exceeded")
        mock_genai = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_types = MagicMock()
        mock_google = MagicMock()
        mock_google.genai = mock_genai
        m = _reload_news()
        with patch.object(m, "_get_api_key", return_value="test-key"), \
             patch.object(m, "fetch_ticker_headlines", return_value=["a headline"]), \
             patch.dict(sys.modules, {"google": mock_google, "google.genai": mock_genai, "google.genai.types": mock_types}):
            result = m.generate_news_summary(["NVDA"], "2026-04-25")
        assert result == ""
