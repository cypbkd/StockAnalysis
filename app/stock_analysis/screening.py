from dataclasses import dataclass
from datetime import date, datetime, timezone as _utc_tz
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from stock_analysis.rules import CanonicalRule, RuleCondition


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class ConditionEvaluation:
    condition: RuleCondition
    matched: bool
    reason: str
    left_value: Any = None
    right_value: Any = None


@dataclass(frozen=True)
class ScreeningResult:
    symbol: str
    matched: bool
    score: float
    metrics: Mapping[str, Any]
    matched_conditions: Tuple[ConditionEvaluation, ...]
    failed_conditions: Tuple[ConditionEvaluation, ...]


@dataclass(frozen=True)
class ReportWatchlist:
    watchlist_id: str
    name: str
    symbols: Tuple[str, ...]
    priority: str
    rule_summary: str


@dataclass(frozen=True)
class OptionIdea:
    symbol: str
    strategy: str
    expiration: str
    score: float
    reason: str
    strike: Optional[float] = None
    highlighted: bool = False


class DeterministicScreeningEngine:
    def evaluate(self, snapshot: MarketSnapshot, rule: CanonicalRule) -> ScreeningResult:
        matched_conditions = []
        failed_conditions = []
        matched_count = 0

        for condition in rule.conditions:
            evaluation = self._evaluate_condition(snapshot, condition)
            if evaluation.matched:
                matched_count += 1
                matched_conditions.append(evaluation)
            else:
                failed_conditions.append(evaluation)

        if rule.logic == "and":
            matched = len(failed_conditions) == 0
        else:
            matched = len(matched_conditions) > 0

        score = float(matched_count) / float(len(rule.conditions))
        return ScreeningResult(
            symbol=snapshot.symbol,
            matched=matched,
            score=score,
            metrics=dict(snapshot.metrics),
            matched_conditions=tuple(matched_conditions),
            failed_conditions=tuple(failed_conditions),
        )

    def screen(self, snapshots: Sequence[MarketSnapshot], rule: CanonicalRule) -> List[ScreeningResult]:
        results = [self.evaluate(snapshot, rule) for snapshot in snapshots]
        return sorted(results, key=lambda result: (-int(result.matched), -result.score, result.symbol))

    def _evaluate_condition(self, snapshot: MarketSnapshot, condition: RuleCondition) -> ConditionEvaluation:
        left_value = snapshot.metrics.get(condition.field)
        if left_value is None:
            return ConditionEvaluation(
                condition=condition,
                matched=False,
                reason="missing field: %s" % condition.field,
            )

        if condition.value_from is not None:
            right_value = snapshot.metrics.get(condition.value_from)
            if right_value is None:
                return ConditionEvaluation(
                    condition=condition,
                    matched=False,
                    reason="right-hand value is missing or unsupported",
                    left_value=left_value,
                )
        else:
            right_value = condition.value

        matched = self._compare(left_value, condition.op, right_value)
        if matched:
            rhs_label = condition.value_from or str(right_value)
            if isinstance(left_value, float) and isinstance(right_value, float):
                reason = "%s %.2f %s %.2f" % (condition.field, left_value, condition.op, right_value)
            else:
                reason = "%s %s %s %s" % (condition.field, condition.op, rhs_label, right_value if condition.value_from else "")
            reason = reason.strip()
        else:
            reason = "%r %s %r is false" % (left_value, condition.op, right_value)
        return ConditionEvaluation(
            condition=condition,
            matched=matched,
            reason=reason,
            left_value=left_value,
            right_value=right_value,
        )

    @staticmethod
    def _compare(left_value: Any, operator: str, right_value: Any) -> bool:
        if operator == ">":
            return left_value > right_value
        if operator == ">=":
            return left_value >= right_value
        if operator == "<":
            return left_value < right_value
        if operator == "<=":
            return left_value <= right_value
        if operator == "==":
            return left_value == right_value
        if operator == "!=":
            return left_value != right_value
        if operator == "in":
            return left_value in right_value
        if operator == "not in":
            return left_value not in right_value
        raise ValueError("unsupported operator: %s" % operator)


def build_nightly_report(
    trade_date: date,
    timezone: str,
    watchlists: Sequence[ReportWatchlist],
    stock_results: Sequence[ScreeningResult],
    option_ideas: Sequence[OptionIdea],
    earnings_watch: Sequence[Mapping[str, Any]],
    active_rules: Sequence[CanonicalRule],
    highlights: Sequence[str],
    report_history: Sequence[Mapping[str, Any]] = (),
    universe_name: str = "SPY 500",
    news_summary: str = "",
) -> Dict[str, Any]:
    watchlist_symbol_count = sum(len(watchlist.symbols) for watchlist in watchlists)
    matched_results = [result for result in stock_results if result.matched]

    return {
        "reportLabel": "Nightly Stock Analysis Report",
        "reportDate": trade_date.isoformat(),
        "generatedAt": datetime.now(_utc_tz.utc).replace(microsecond=0).isoformat() + "Z",
        "timezone": timezone,
        "universe": {
            "name": universe_name,
            "totalSymbols": watchlist_symbol_count,
            "activeLists": [watchlist.name for watchlist in watchlists],
        },
        "summary": {
            "totalSymbols": watchlist_symbol_count,
            "matchedSignals": len(matched_results),
            "highPrioritySignals": sum(
                1 for result in matched_results
                if _result_status(result, result.metrics.get("match_count", 1)) == "high priority"
            ),
            "optionsCandidates": len(option_ideas),
            "earningsWatchCount": len(earnings_watch),
        },
        "highlights": list(highlights),
        "newsSummary": news_summary,
        "reportHistory": list(report_history),
        "watchlists": [
            {
                "id": watchlist.watchlist_id,
                "name": watchlist.name,
                "symbols": len(watchlist.symbols),
                "ruleSummary": watchlist.rule_summary,
                "priority": watchlist.priority,
            }
            for watchlist in watchlists
        ],
        "stockSignals": [_result_to_signal(result) for result in matched_results],
        "optionsSignals": [
            {
                "symbol": idea.symbol,
                "strategy": idea.strategy,
                "expiration": idea.expiration,
                "score": round(idea.score, 1),
                "reason": idea.reason,
                "strike": idea.strike,
                "highlighted": idea.highlighted,
            }
            for idea in option_ideas
        ],
        "earningsWatch": list(earnings_watch),
        "ruleSets": [
            {
                "id": rule.name.lower().replace(" ", "-") if rule.name else f"rule-{index + 1}",
                "name": rule.name or f"Rule {index + 1}",
                "universe": universe_name,
                "description": rule.description or "Structured nightly screener rule",
                "naturalLanguage": rule.source_text or "No natural-language source provided.",
            }
            for index, rule in enumerate(active_rules)
        ],
    }


def _result_to_signal(result: ScreeningResult) -> Dict[str, Any]:
    reasons = [evaluation.reason for evaluation in result.matched_conditions]
    metrics = result.metrics

    return {
        "symbol": result.symbol,
        "companyName": metrics.get("company_name", result.symbol),
        "watchlists": metrics.get("watchlists", []),
        "ruleNames": metrics.get("rule_names") or ([metrics["rule_name"]] if metrics.get("rule_name") else []),
        "score": round(result.score * 100),
        "lastPrice": metrics.get("close", 0.0),
        "changePercent": metrics.get("change_percent", 0.0),
        "reason": "; ".join(reasons) if reasons else "Matched the active rules.",
        "status": _result_status(result, metrics.get("match_count", 1)),
        "technicalData": _extract_technical_data(metrics),
    }


def _extract_technical_data(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    """Key technical metrics stored in the signal for on-demand AI analysis."""
    fields = {
        "volumeRatio": "volume_ratio",
        "rsi14": "rsi_14",
        "ema20": "ema_20",
        "sma20": "sma_20",
        "sma50": "sma_50",
        "high52w": "high_52w",
        "low52w": "low_52w",
        "pivotR1": "pivot_r1",
        "pivotR2": "pivot_r2",
        "pivotS1": "pivot_s1",
        "pivotS2": "pivot_s2",
        "earningsDate": "earnings_date",
        "earningsInDays": "earnings_in_days",
        "earningsTiming": "earnings_timing",
    }
    return {camel: metrics[snake] for camel, snake in fields.items() if metrics.get(snake) is not None}


def _result_status(result: ScreeningResult, match_count: int = 1) -> str:
    if match_count >= 5:
        return "high priority"
    if result.score >= 0.5:
        return "matched"
    return "watch"
