from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


SUPPORTED_FIELDS = {
    "close",
    "open",
    "high",
    "low",
    "volume",
    "avg_volume_20d",
    "change_percent",
    "rsi_14",
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_20",
    "prev_sma_20",
    "prev_sma_50",
    "earnings_in_days",
    "relative_strength_20d",
    "option_volume",
    "open_interest",
    "days_to_expiration",
    "macd",
    "atr_14",
    "high_52w",
    "low_52w",
    "volume_ratio",
    "close_to_ath_pct",
    "close_to_support_pct",
    "pivot_point",
    "pivot_r1",
    "pivot_r2",
    "pivot_s1",
    "pivot_s2",
    "close_to_s1_pct",
    "close_to_r1_pct",
    "td_buy_setup",
    "td_sell_setup",
}

SUPPORTED_OPERATORS = {"<", "<=", ">", ">=", "==", "!=", "in", "not in"}


class RuleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RuleCondition:
    field: str
    op: str
    value: Any = None
    value_from: Optional[str] = None

    def normalized(self) -> "RuleCondition":
        return RuleCondition(
            field=self.field.strip().lower(),
            op=self.op.strip().lower(),
            value=self.value,
            value_from=self.value_from.strip().lower() if self.value_from else None,
        )


@dataclass(frozen=True)
class CanonicalRule:
    logic: str
    conditions: Tuple[RuleCondition, ...] = field(default_factory=tuple)
    name: Optional[str] = None
    source_text: Optional[str] = None
    description: Optional[str] = None
    version: int = 1

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "CanonicalRule":
        logic = str(mapping.get("logic", "and")).strip().lower()
        name = mapping.get("name")
        source_text = mapping.get("source_text")
        description = mapping.get("description")
        version = int(mapping.get("version", 1))
        raw_conditions = mapping.get("conditions", [])
        conditions = []
        for raw_condition in raw_conditions:
            condition = RuleCondition(
                field=raw_condition.get("field", ""),
                op=raw_condition.get("op", ""),
                value=raw_condition.get("value"),
                value_from=raw_condition.get("value_from"),
            ).normalized()
            conditions.append(condition)
        rule = cls(
            logic=logic,
            conditions=tuple(conditions),
            name=name,
            source_text=source_text,
            description=description,
            version=version,
        )
        rule.validate()
        return rule

    def validate(self) -> None:
        if self.logic not in {"and", "or"}:
            raise RuleValidationError("logic must be either 'and' or 'or'")
        if not self.conditions:
            raise RuleValidationError("canonical rule needs at least one condition")
        for condition in self.conditions:
            self._validate_condition(condition)

    def _validate_condition(self, condition: RuleCondition) -> None:
        if condition.field not in SUPPORTED_FIELDS:
            raise RuleValidationError("unsupported field: %s" % condition.field)
        if condition.op not in SUPPORTED_OPERATORS:
            raise RuleValidationError("unsupported operator: %s" % condition.op)
        has_value = condition.value is not None
        has_value_from = condition.value_from is not None
        if has_value == has_value_from:
            raise RuleValidationError("condition must define exactly one of value or value_from")

    def to_mapping(self) -> Mapping[str, Any]:
        payload = {
            "logic": self.logic,
            "conditions": [],
            "version": self.version,
        }
        if self.name is not None:
            payload["name"] = self.name
        if self.source_text is not None:
            payload["source_text"] = self.source_text
        if self.description is not None:
            payload["description"] = self.description
        payload["conditions"] = [self._condition_to_mapping(condition) for condition in self.conditions]
        return payload

    @staticmethod
    def _condition_to_mapping(condition: RuleCondition) -> Mapping[str, Any]:
        payload = {
            "field": condition.field,
            "op": condition.op,
        }
        if condition.value_from is not None:
            payload["value_from"] = condition.value_from
        else:
            payload["value"] = condition.value
        return payload
