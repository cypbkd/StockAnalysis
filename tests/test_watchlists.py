"""Unit tests for load_watchlists() — DynamoDB-backed watchlist loading, and COMPANY_NAMES JSON loading."""
import sys
import pytest
from unittest.mock import MagicMock, patch


# ── COMPANY_NAMES JSON loading ─────────────────────────────────────────────────

def test_company_names_loads_from_json():
    """COMPANY_NAMES must be loaded from company_names.json, not empty."""
    import importlib
    import stock_analysis.data as data_mod
    importlib.reload(data_mod)
    assert len(data_mod.COMPANY_NAMES) > 300, "Expected 300+ entries from company_names.json"


def test_company_names_contains_known_tickers():
    import stock_analysis.data as data_mod
    for ticker, expected in [("AAPL", "Apple"), ("NVDA", "NVIDIA"), ("MSFT", "Microsoft")]:
        assert data_mod.COMPANY_NAMES.get(ticker) == expected, \
            f"Expected {ticker} -> {expected}, got {data_mod.COMPANY_NAMES.get(ticker)}"


def test_company_names_includes_nasdaq_entries():
    """NASDAQ-sourced tickers (beyond the old hardcoded set) should be present."""
    import stock_analysis.data as data_mod
    # These are tickers that exist in nasdaq_tickers.json but weren't in the old hardcoded dict
    for ticker in ["AAL", "CROX", "ROKU"]:
        assert ticker in data_mod.COMPANY_NAMES, f"{ticker} missing from COMPANY_NAMES"


# ── boto3 stub (not installed locally; only present in the Lambda layer) ─────

def _make_boto3_stub(items, paginated=False):
    """Return a sys.modules-compatible boto3 stub whose Table scan() returns items."""
    table = MagicMock()
    if paginated:
        table.scan.side_effect = [
            {"Items": items[:1], "LastEvaluatedKey": {"watchlistId": {"S": "page1"}}},
            {"Items": items[1:]},
        ]
    else:
        table.scan.return_value = {"Items": items}

    conditions_mod = MagicMock()
    conditions_mod.Attr.return_value = MagicMock()

    boto3_stub = MagicMock()
    boto3_stub.resource.return_value.Table.return_value = table
    return boto3_stub, conditions_mod, table


_FANG_ITEM = {
    "watchlistId": "fang",
    "version": "latest",
    "name": "FANG+",
    "tickers": ["META", "AMZN", "NFLX", "GOOGL"],
}

_LAOLI_ITEM = {
    "watchlistId": "laoli",
    "version": "latest",
    "name": "Lao Li",
    "tickers": ["TSLA", "NVDA", "AAPL"],
}


def _run(items, *, paginated=False):
    boto3_stub, conditions_mod, table = _make_boto3_stub(items, paginated=paginated)
    with patch.dict(sys.modules, {"boto3": boto3_stub, "boto3.dynamodb.conditions": conditions_mod}):
        from stock_analysis.data import load_watchlists
        result = load_watchlists("dev-watchlists")
    return result, table


def test_load_watchlists_returns_correct_shape():
    result, _ = _run([_FANG_ITEM, _LAOLI_ITEM])
    assert set(result.keys()) == {"fang", "laoli"}
    assert result["fang"]["name"] == "FANG+"
    assert result["fang"]["tickers"] == ["META", "AMZN", "NFLX", "GOOGL"]
    assert result["laoli"]["name"] == "Lao Li"
    assert result["laoli"]["tickers"] == ["TSLA", "NVDA", "AAPL"]


def test_load_watchlists_preserves_name():
    """The watchlist display name from DynamoDB must survive the load."""
    result, _ = _run([_LAOLI_ITEM])
    assert result["laoli"]["name"] == "Lao Li"


def test_load_watchlists_handles_pagination():
    result, table = _run([_FANG_ITEM, _LAOLI_ITEM], paginated=True)
    assert len(result) == 2
    assert "fang" in result
    assert "laoli" in result
    assert table.scan.call_count == 2


def test_load_watchlists_empty_table():
    result, _ = _run([])
    assert result == {}


def test_load_watchlists_uses_correct_table_name():
    boto3_stub, conditions_mod, _ = _make_boto3_stub([_FANG_ITEM])
    with patch.dict(sys.modules, {"boto3": boto3_stub, "boto3.dynamodb.conditions": conditions_mod}):
        from stock_analysis.data import load_watchlists
        load_watchlists("dev-watchlists")
    boto3_stub.resource.return_value.Table.assert_called_once_with("dev-watchlists")


def test_load_watchlists_tickers_is_list():
    """tickers must be a plain list even when DynamoDB returns other iterables."""
    item = {**_FANG_ITEM, "tickers": tuple(_FANG_ITEM["tickers"])}
    result, _ = _run([item])
    assert isinstance(result["fang"]["tickers"], list)


# ── Integration test (skipped unless --integration flag passed) ──────────────

def test_load_watchlists_integration(request):
    """Reads from the real dev-watchlists DynamoDB table.

    Run with: pytest tests/test_watchlists.py --integration
    Requires AWS credentials (profile: stock-screener) and a seeded dev-watchlists table.
    Seed first with: ./scripts/seed-watchlists.sh
    """
    if not request.config.getoption("--integration", default=False):
        pytest.skip("pass --integration to run against real AWS")

    import importlib
    import stock_analysis.data as data_mod
    importlib.reload(data_mod)
    result = data_mod.load_watchlists("dev-watchlists")

    assert len(result) >= 1, "dev-watchlists table must have at least one watchlist"
    for wl_id, wl in result.items():
        assert isinstance(wl["name"], str) and wl["name"], f"{wl_id} missing name"
        assert isinstance(wl["tickers"], list) and wl["tickers"], f"{wl_id} missing tickers"
