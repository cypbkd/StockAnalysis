from dataclasses import dataclass
from typing import List, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class TickerChunk:
    chunk_id: str
    tickers: List[str]


@dataclass(frozen=True)
class ChunkManifest:
    watchlist_ids: Tuple[str, ...]
    total_symbols: int
    chunks: List[TickerChunk]


@dataclass
class TickerChunker:
    chunk_size: int
    prefix: str = "chunk"

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")

    def chunk(self, tickers: Sequence[str]) -> List[TickerChunk]:
        ordered = [ticker for ticker in tickers]
        chunks = []
        for index in range(0, len(ordered), self.chunk_size):
            chunk_number = len(chunks) + 1
            chunk_id = f"{self.prefix}-{chunk_number:03d}"
            chunks.append(
                TickerChunk(
                    chunk_id=chunk_id,
                    tickers=ordered[index : index + self.chunk_size],
                )
            )
        return chunks


def build_chunk_manifest(
    watchlist_symbols: Mapping[str, Sequence[str]],
    chunk_size: int,
    prefix: str = "chunk",
) -> ChunkManifest:
    normalized_watchlist_ids = tuple(sorted(watchlist_symbols.keys()))
    unique_symbols = sorted(
        {
            symbol.strip().upper()
            for symbols in watchlist_symbols.values()
            for symbol in symbols
            if symbol and symbol.strip()
        }
    )
    chunker = TickerChunker(chunk_size=chunk_size, prefix=prefix)
    return ChunkManifest(
        watchlist_ids=normalized_watchlist_ids,
        total_symbols=len(unique_symbols),
        chunks=chunker.chunk(unique_symbols),
    )
