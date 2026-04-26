import pytest

from stock_analysis.chunking import TickerChunker, build_chunk_manifest


def test_chunker_preserves_order_and_uses_stable_ids():
    chunker = TickerChunker(chunk_size=3, prefix="worker")

    chunks = chunker.chunk(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])

    assert [chunk.chunk_id for chunk in chunks] == ["worker-001", "worker-002"]
    assert [chunk.tickers for chunk in chunks] == [
        ["AAPL", "MSFT", "GOOGL"],
        ["AMZN", "NVDA"],
    ]


def test_chunker_rejects_non_positive_chunk_sizes():
    with pytest.raises(ValueError, match="chunk_size must be greater than zero"):
        TickerChunker(chunk_size=0)


def test_build_chunk_manifest_flattens_unique_symbols_across_watchlists():
    manifest = build_chunk_manifest(
        {
            "spy500": ["AAPL", "MSFT", "NVDA"],
            "fang": ["META", "MSFT", "AMZN"],
        },
        chunk_size=2,
        prefix="nightly",
    )

    assert manifest.total_symbols == 5
    assert manifest.watchlist_ids == ("fang", "spy500")
    assert [chunk.chunk_id for chunk in manifest.chunks] == [
        "nightly-001",
        "nightly-002",
        "nightly-003",
    ]
    assert manifest.chunks[0].tickers == ["AAPL", "AMZN"]
    assert manifest.chunks[2].tickers == ["NVDA"]
