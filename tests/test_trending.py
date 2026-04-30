"""Unit tests for stock_analysis.trending."""
import json
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# fetch_yahoo_trending
# ---------------------------------------------------------------------------

class TestFetchYahooTrending:
    def _make_response(self, symbols):
        payload = {
            "finance": {
                "result": [{"quotes": [{"symbol": s} for s in symbols]}]
            }
        }
        return json.dumps(payload).encode()

    def test_returns_symbols_list(self):
        from stock_analysis.trending import fetch_yahoo_trending
        raw = self._make_response(["NVDA", "TSLA", "AAPL"])
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_yahoo_trending(count=10)
        assert result == ["NVDA", "TSLA", "AAPL"]

    def test_caps_at_count(self):
        from stock_analysis.trending import fetch_yahoo_trending
        symbols = [f"SYM{i}" for i in range(20)]
        raw = self._make_response(symbols)
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_yahoo_trending(count=5)
        assert len(result) == 5
        assert result == symbols[:5]

    def test_returns_empty_on_network_error(self):
        from stock_analysis.trending import fetch_yahoo_trending
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = fetch_yahoo_trending()
        assert result == []

    def test_returns_empty_on_malformed_json(self):
        from stock_analysis.trending import fetch_yahoo_trending
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_yahoo_trending()
        assert result == []

    def test_filters_symbols_without_key(self):
        from stock_analysis.trending import fetch_yahoo_trending
        payload = {
            "finance": {
                "result": [{"quotes": [{"symbol": "NVDA"}, {}, {"symbol": "AAPL"}]}]
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_yahoo_trending()
        assert result == ["NVDA", "AAPL"]


# ---------------------------------------------------------------------------
# _fetch_price_data
# ---------------------------------------------------------------------------

class TestFetchPriceData:
    def _make_hist(self, closes, volumes=None):
        import pandas as pd
        if volumes is None:
            volumes = [1_000_000] * len(closes)
        index = pd.date_range("2026-04-20", periods=len(closes), freq="B")
        return pd.DataFrame({"Close": closes, "Volume": volumes}, index=index)

    def test_returns_price_metrics(self):
        from stock_analysis import trending as m
        hist = self._make_hist([100.0, 102.0, 104.0, 106.0, 110.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = hist
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        with patch.dict(__import__("sys").modules, {"yfinance": mock_yf}):
            result = m._fetch_price_data("NVDA")
        assert result is not None
        assert result["lastPrice"] == 110.0
        # 1d: (110 - 106) / 106 * 100
        assert abs(result["change1d"] - (110 / 106 - 1) * 100) < 0.01
        # 3d: from closes[1] (4 rows before last) to last
        assert abs(result["change3d"] - (110 / 102 - 1) * 100) < 0.01

    def test_returns_none_on_empty_history(self):
        import pandas as pd
        from stock_analysis import trending as m
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        with patch.dict(__import__("sys").modules, {"yfinance": mock_yf}):
            result = m._fetch_price_data("UNKNOWN")
        assert result is None

    def test_returns_none_on_exception(self):
        from stock_analysis import trending as m
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = Exception("rate limit")
        with patch.dict(__import__("sys").modules, {"yfinance": mock_yf}):
            result = m._fetch_price_data("BOOM")
        assert result is None

    def test_volume_ratio_computed(self):
        from stock_analysis import trending as m
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        # today vol = 2M, prior avg = 1M → ratio should be ~2.0
        volumes = [1_000_000, 1_000_000, 1_000_000, 1_000_000, 2_000_000]
        hist = self._make_hist(closes, volumes)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = hist
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        with patch.dict(__import__("sys").modules, {"yfinance": mock_yf}):
            result = m._fetch_price_data("AAPL")
        assert result is not None
        assert abs(result["volumeRatio"] - 2.0) < 0.01


# ---------------------------------------------------------------------------
# build_trending_tickers
# ---------------------------------------------------------------------------

class TestBuildTrendingTickers:
    def _make_price_data(self):
        return {"lastPrice": 150.0, "change1d": 2.5, "change3d": 5.0, "volumeRatio": 1.5}

    def test_returns_enriched_list(self):
        from stock_analysis import trending as m
        names = {"NVDA": "NVIDIA Corporation", "TSLA": "Tesla Inc."}
        with patch.object(m, "fetch_yahoo_trending", return_value=["NVDA", "TSLA"]):
            with patch.object(m, "_fetch_price_data", return_value=self._make_price_data()):
                with patch.object(m, "COMPANY_NAMES", names):
                    with patch.object(m, "fetch_ticker_headlines", return_value=["Headline one"]):
                        result = m.build_trending_tickers("2026-04-25")
        assert len(result) == 2
        assert result[0]["symbol"] == "NVDA"
        assert result[0]["companyName"] == "NVIDIA Corporation"
        assert result[0]["trendRank"] == 1
        assert result[0]["lastPrice"] == 150.0
        assert result[0]["headlines"] == ["Headline one"]

    def test_skips_tickers_with_no_price_data(self):
        from stock_analysis import trending as m
        price_side_effect = [None, self._make_price_data()]
        with patch.object(m, "fetch_yahoo_trending", return_value=["BAD", "GOOD"]):
            with patch.object(m, "_fetch_price_data", side_effect=price_side_effect):
                with patch.object(m, "COMPANY_NAMES", {}):
                    with patch.object(m, "fetch_ticker_headlines", return_value=[]):
                        result = m.build_trending_tickers("2026-04-25")
        assert len(result) == 1
        assert result[0]["symbol"] == "GOOD"

    def test_caps_at_max_tickers(self):
        from stock_analysis import trending as m
        symbols = [f"SYM{i}" for i in range(20)]
        with patch.object(m, "fetch_yahoo_trending", return_value=symbols):
            with patch.object(m, "_fetch_price_data", return_value=self._make_price_data()):
                with patch.object(m, "COMPANY_NAMES", {}):
                    with patch.object(m, "fetch_ticker_headlines", return_value=[]):
                        result = m.build_trending_tickers("2026-04-25", max_tickers=5)
        assert len(result) == 5

    def test_returns_empty_when_no_trending_symbols(self):
        from stock_analysis import trending as m
        with patch.object(m, "fetch_yahoo_trending", return_value=[]):
            result = m.build_trending_tickers("2026-04-25")
        assert result == []

    def test_trendrank_reflects_yahoo_position(self):
        from stock_analysis import trending as m
        with patch.object(m, "fetch_yahoo_trending", return_value=["A", "B", "C"]):
            with patch.object(m, "_fetch_price_data", return_value=self._make_price_data()):
                with patch.object(m, "COMPANY_NAMES", {}):
                    with patch.object(m, "fetch_ticker_headlines", return_value=[]):
                        result = m.build_trending_tickers("2026-04-25")
        assert [r["trendRank"] for r in result] == [1, 2, 3]

    def test_uses_symbol_as_company_name_when_unknown(self):
        from stock_analysis import trending as m
        with patch.object(m, "fetch_yahoo_trending", return_value=["XYZ"]):
            with patch.object(m, "_fetch_price_data", return_value=self._make_price_data()):
                with patch.object(m, "COMPANY_NAMES", {}):
                    with patch.object(m, "fetch_ticker_headlines", return_value=[]):
                        result = m.build_trending_tickers("2026-04-25")
        assert result[0]["companyName"] == "XYZ"
