import pytest

from stock_analysis.rules import CanonicalRule, RuleValidationError


def test_canonical_rule_normalizes_and_round_trips():
    rule = CanonicalRule.from_mapping(
        {
            "logic": "AND",
            "name": "Momentum",
            "source_text": "Find stocks above the 20DMA and not overbought.",
            "conditions": [
                {"field": "close", "op": ">", "value_from": "sma_20"},
                {"field": "rsi_14", "op": "<", "value": 70},
            ],
        }
    )

    assert rule.logic == "and"
    assert rule.name == "Momentum"
    assert rule.conditions[0].value_from == "sma_20"
    assert rule.to_mapping() == {
        "logic": "and",
        "name": "Momentum",
        "source_text": "Find stocks above the 20DMA and not overbought.",
        "version": 1,
        "conditions": [
            {"field": "close", "op": ">", "value_from": "sma_20"},
            {"field": "rsi_14", "op": "<", "value": 70},
        ],
    }


def test_canonical_rule_rejects_unknown_field():
    with pytest.raises(RuleValidationError, match="unsupported field"):
        CanonicalRule.from_mapping(
            {
                "logic": "and",
                "conditions": [{"field": "magic_signal", "op": ">", "value": 1}],
            }
        )


def test_canonical_rule_rejects_missing_conditions():
    with pytest.raises(RuleValidationError, match="at least one condition"):
        CanonicalRule.from_mapping({"logic": "and", "conditions": []})
