from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable, Tuple


class CacheAction(str, Enum):
    REUSE = "reuse"
    FETCH_ALL = "fetch_all"
    FETCH_MISSING = "fetch_missing"


@dataclass(frozen=True)
class CacheRequest:
    dataset: str
    trading_date: date
    source: str
    symbols: Tuple[str, ...] = field(default_factory=tuple)

    def normalized_symbols(self) -> Tuple[str, ...]:
        seen = set()
        ordered = []
        for symbol in self.symbols:
            symbol = symbol.strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
        return tuple(ordered)


@dataclass(frozen=True)
class CacheDecision:
    request: CacheRequest
    action: CacheAction
    required_keys: Tuple[str, ...]
    existing_keys: Tuple[str, ...]
    missing_keys: Tuple[str, ...]
    reason: str


class S3CachePlanner:
    def __init__(self, bucket: str, raw_prefix: str = "raw"):
        self.bucket = bucket
        self.raw_prefix = raw_prefix.strip("/")

    def cache_key_for_symbol(self, request: CacheRequest, symbol: str) -> str:
        normalized_symbol = symbol.strip().upper()
        return (
            f"{self.raw_prefix}/{request.dataset}/date={request.trading_date.isoformat()}"
            f"/source={request.source}/symbol={normalized_symbol}.json"
        )

    def cache_key_for_request(self, request: CacheRequest) -> str:
        symbols = request.normalized_symbols()
        if not symbols:
            return (
                f"{self.raw_prefix}/{request.dataset}/date={request.trading_date.isoformat()}"
                f"/source={request.source}/calendar.json"
            )
        if len(symbols) == 1:
            return self.cache_key_for_symbol(request, symbols[0])
        raise ValueError("symbol-specific requests with multiple symbols need per-symbol keys")

    def required_keys_for_request(self, request: CacheRequest) -> Tuple[str, ...]:
        symbols = request.normalized_symbols()
        if not symbols:
            return (self.cache_key_for_request(request),)
        return tuple(self.cache_key_for_symbol(request, symbol) for symbol in symbols)

    def plan(self, request: CacheRequest, existing_keys: Iterable[str]) -> CacheDecision:
        required_keys = self.required_keys_for_request(request)
        existing_lookup = set(existing_keys)
        existing = tuple(key for key in required_keys if key in existing_lookup)
        missing = tuple(key for key in required_keys if key not in existing_lookup)

        if not missing:
            action = CacheAction.REUSE
            reason = "all requested raw snapshots already exist"
        elif not existing:
            action = CacheAction.FETCH_ALL
            reason = "no raw cache hit"
        else:
            action = CacheAction.FETCH_MISSING
            reason = "partial raw cache hit"

        return CacheDecision(
            request=request,
            action=action,
            required_keys=required_keys,
            existing_keys=existing,
            missing_keys=missing,
            reason=reason,
        )
