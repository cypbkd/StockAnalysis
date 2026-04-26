#!/usr/bin/env bash
# Manually triggers the nightly analysis pipeline for a given date.
# Invokes coordinator → waits for workers → invokes aggregator.
#
# Usage:
#   ./scripts/run-analysis.sh                  # today's date, default wait
#   ./scripts/run-analysis.sh --date 2026-04-23
#   ./scripts/run-analysis.sh --wait 600       # override worker wait (seconds)
#   ./scripts/run-analysis.sh --date 2026-04-23 --wait 120
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
AWS_REGION="us-west-2"
CDK_STACK="StockAnalysisInfraDev"
S3_BUCKET="stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd"
CF_DISTRIBUTION="E2IOLFNFUVHVKE"
WORKER_WAIT=300   # seconds to wait for workers before running aggregator
RUN_DATE="$(date +%Y-%m-%d)"

# ── Arg parsing ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)  RUN_DATE="$2"; shift 2 ;;
    --wait)  WORKER_WAIT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

step() { echo; echo "▶ $*"; }
ok()   { echo "  ✓ $*"; }
fail() { echo; echo "✗ $*" >&2; exit 1; }

check_lambda_response() {
  local file="$1" label="$2"
  if [[ ! -s "$file" ]]; then
    fail "$label: empty response"
  fi
  # Lambda sets x-amz-function-error header → AWS CLI writes FunctionError field
  if grep -q '"FunctionError"' "$file" 2>/dev/null; then
    echo "  Response: $(cat "$file")"
    fail "$label returned a function error"
  fi
  ok "$label succeeded"
}

# ── Resolve Lambda function names from CloudFormation outputs ──────────────────
step "Resolving Lambda names from CloudFormation"
COORDINATOR_FN=$(AWS_PROFILE="$AWS_PROFILE" aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$CDK_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CoordinatorFunctionName'].OutputValue" \
  --output text)

AGGREGATOR_FN=$(AWS_PROFILE="$AWS_PROFILE" aws cloudformation describe-stacks \
  --region "$AWS_REGION" \
  --stack-name "$CDK_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='AggregatorFunctionName'].OutputValue" \
  --output text)

[[ -z "$COORDINATOR_FN" ]] && fail "Could not resolve CoordinatorFunctionName from stack $CDK_STACK"
[[ -z "$AGGREGATOR_FN" ]] && fail "Could not resolve AggregatorFunctionName from stack $CDK_STACK"
ok "Coordinator: $COORDINATOR_FN"
ok "Aggregator:  $AGGREGATOR_FN"

# ── Step 1: Coordinator ────────────────────────────────────────────────────────
step "Invoking coordinator for $RUN_DATE"
COORD_OUT="/tmp/coord-out-$$.json"
AWS_PROFILE="$AWS_PROFILE" aws lambda invoke \
  --region "$AWS_REGION" \
  --cli-binary-format raw-in-base64-out \
  --function-name "$COORDINATOR_FN" \
  --payload "{\"run_date\":\"$RUN_DATE\"}" \
  "$COORD_OUT" > /dev/null
echo "  Response: $(cat "$COORD_OUT")"
check_lambda_response "$COORD_OUT" "Coordinator"

# ── Step 2: Wait for workers ───────────────────────────────────────────────────
step "Waiting ${WORKER_WAIT}s for workers to finish"
echo -n "  "
for ((i=WORKER_WAIT; i>0; i--)); do
  if (( i % 30 == 0 )); then
    echo -n "${i}s "
  else
    echo -n "."
  fi
  sleep 1
done
echo " done"

# ── Step 3: Aggregator (with retry on throttle) ────────────────────────────────
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
check_lambda_response "$AGG_OUT" "Aggregator"

# ── Done ───────────────────────────────────────────────────────────────────────
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Analysis complete for $RUN_DATE"
echo "  https://d2r08g384yeqpo.cloudfront.net"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
