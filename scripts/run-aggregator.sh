#!/usr/bin/env bash
# Manually invokes just the aggregator Lambda (skips coordinator + workers).
# Use this when workers have already run and you only need to regenerate the report.
#
# Usage:
#   ./scripts/run-aggregator.sh                  # today's date
#   ./scripts/run-aggregator.sh --date 2026-04-26
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
AWS_REGION="us-west-2"
CDK_STACK="StockAnalysisInfraDev"
RUN_DATE="$(date +%Y-%m-%d)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) RUN_DATE="$2"; shift 2 ;;
    *) echo "Usage: $0 [--date YYYY-MM-DD]" >&2; exit 1 ;;
  esac
done

step() { echo; echo "▶ $*"; }
ok()   { echo "  ✓ $*"; }
fail() { echo; echo "✗ $*" >&2; exit 1; }

step "Resolving aggregator function name"
AGGREGATOR_FN=$(AWS_PROFILE="$AWS_PROFILE" aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$CDK_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='AggregatorFunctionName'].OutputValue" \
  --output text)
[[ -z "$AGGREGATOR_FN" ]] && fail "Could not resolve AggregatorFunctionName from stack $CDK_STACK"
ok "$AGGREGATOR_FN"

step "Invoking aggregator for $RUN_DATE"
AGG_OUT="/tmp/agg-out-$$.json"
AGG_RETRIES=5
AGG_RETRY_DELAY=30
for ((attempt=1; attempt<=AGG_RETRIES; attempt++)); do
  AGG_ERROR=$(AWS_PROFILE="$AWS_PROFILE" aws lambda invoke \
    --region "$AWS_REGION" \
    --cli-binary-format raw-in-base64-out \
    --function-name "$AGGREGATOR_FN" \
    --payload "{\"run_date\":\"$RUN_DATE\"}" \
    "$AGG_OUT" 2>&1) && break
  if echo "$AGG_ERROR" | grep -q "TooManyRequestsException\|Rate Exceeded"; then
    echo "  Rate limited, retrying in ${AGG_RETRY_DELAY}s (attempt $attempt/$AGG_RETRIES)..."
    sleep "$AGG_RETRY_DELAY"
  else
    echo "$AGG_ERROR" >&2
    fail "Aggregator invoke failed"
  fi
  [[ $attempt -eq $AGG_RETRIES ]] && fail "Aggregator still rate-limited after $AGG_RETRIES attempts"
done

echo "  Response: $(cat "$AGG_OUT")"
if grep -q '"FunctionError"' "$AGG_OUT" 2>/dev/null; then
  fail "Aggregator returned a function error"
fi
ok "Aggregator succeeded"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Report regenerated for $RUN_DATE"
echo "  https://d2r08g384yeqpo.cloudfront.net"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
