#!/usr/bin/env bash
# Historical data management CLI for the nightly stock analysis pipeline.
#
# Usage:
#   ./scripts/manage-history.sh delete <date>           # delete all derived + report data
#   ./scripts/manage-history.sh report <date>           # print raw JSON report to stdout
#   ./scripts/manage-history.sh report <date> --pretty  # pretty-print the JSON
#   ./scripts/manage-history.sh regen <date>            # re-run the full pipeline for a date
#   ./scripts/manage-history.sh regen <date> --wait 120 # override worker wait seconds
#
# Options (can be set before or after subcommand):
#   --profile  AWS profile name (default: stock-screener)
#   --bucket   S3 bucket override
#   --stack    CloudFormation stack name for Lambda resolution
#   -y / --yes Skip confirmation prompts
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
AWS_REGION="us-west-2"
CDK_STACK="StockAnalysisInfraDev"
S3_BUCKET="stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd"
WORKER_WAIT=300
YES=false
PRETTY=false

# ── Helpers ────────────────────────────────────────────────────────────────────

step()    { echo; echo "▶ $*"; }
ok()      { echo "  ✓ $*"; }
fail()    { echo; echo "✗ $*" >&2; exit 1; }
info()    { echo "  $*"; }

aws_cmd() { AWS_PROFILE="$AWS_PROFILE" aws --region "$AWS_REGION" "$@"; }

validate_date() {
  local d="$1"
  if ! [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    fail "Date must be YYYY-MM-DD, got: $d"
  fi
  # Validate it's a real date (macOS date -j -f works for this)
  if ! date -j -f "%Y-%m-%d" "$d" &>/dev/null 2>&1; then
    fail "Invalid date: $d"
  fi
}

confirm() {
  local prompt="$1"
  if $YES; then return 0; fi
  printf "%s [y/N] " "$prompt"
  read -r answer
  [[ "$answer" =~ ^[Yy](es)?$ ]]
}

count_s3_prefix() {
  local prefix="$1"
  aws_cmd s3api list-objects-v2 \
    --bucket "$S3_BUCKET" \
    --prefix "$prefix" \
    --query "length(Contents[*])" \
    --output text 2>/dev/null || echo "0"
}

delete_s3_prefix() {
  local prefix="$1"
  aws_cmd s3 rm "s3://${S3_BUCKET}/${prefix}" --recursive --quiet
}

resolve_lambda_names() {
  COORDINATOR_FN=$(aws_cmd cloudformation describe-stacks \
    --stack-name "$CDK_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='CoordinatorFunctionName'].OutputValue" \
    --output text)
  AGGREGATOR_FN=$(aws_cmd cloudformation describe-stacks \
    --stack-name "$CDK_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='AggregatorFunctionName'].OutputValue" \
    --output text)
  [[ -z "$COORDINATOR_FN" ]] && fail "Could not resolve CoordinatorFunctionName from stack $CDK_STACK"
  [[ -z "$AGGREGATOR_FN" ]] && fail "Could not resolve AggregatorFunctionName from stack $CDK_STACK"
}

invoke_lambda() {
  local fn="$1" payload="$2" out_file="$3"
  aws_cmd lambda invoke \
    --cli-binary-format raw-in-base64-out \
    --function-name "$fn" \
    --payload "$payload" \
    "$out_file" > /dev/null
  if grep -q '"FunctionError"' "$out_file" 2>/dev/null; then
    echo "  Response: $(cat "$out_file")" >&2
    fail "Lambda $fn returned a function error"
  fi
}

# ── Subcommand: delete ─────────────────────────────────────────────────────────

cmd_delete() {
  local run_date="$1"
  validate_date "$run_date"

  local prefixes=(
    "derived/chunks/${run_date}/"
    "derived/manifests/${run_date}/"
    "reports/runs/${run_date}/"
  )

  step "Checking objects to delete for $run_date"
  local total=0
  for prefix in "${prefixes[@]}"; do
    local n
    n=$(count_s3_prefix "$prefix")
    [[ "$n" == "None" ]] && n=0
    info "${prefix}  (${n} object(s))"
    total=$((total + n))
  done

  if [[ "$total" -eq 0 ]]; then
    info "Nothing found for $run_date — nothing to delete."
    return
  fi

  confirm "Delete $total object(s) for $run_date?" || { echo "Aborted."; exit 0; }

  step "Deleting data for $run_date"
  for prefix in "${prefixes[@]}"; do
    delete_s3_prefix "$prefix"
    ok "Cleared $prefix"
  done

  echo
  echo "Done. Deleted data for $run_date."
}

# ── Subcommand: report ─────────────────────────────────────────────────────────

cmd_report() {
  local run_date="$1"
  validate_date "$run_date"

  local key="reports/runs/${run_date}/report.json"

  if ! aws_cmd s3api head-object --bucket "$S3_BUCKET" --key "$key" &>/dev/null; then
    fail "No report found for $run_date  (s3://${S3_BUCKET}/${key})"
  fi

  if $PRETTY; then
    aws_cmd s3 cp "s3://${S3_BUCKET}/${key}" - | python3 -m json.tool
  else
    aws_cmd s3 cp "s3://${S3_BUCKET}/${key}" -
  fi
}

# ── Subcommand: regen ──────────────────────────────────────────────────────────

cmd_regen() {
  local run_date="$1"
  validate_date "$run_date"

  step "Resolving Lambda names from stack $CDK_STACK"
  resolve_lambda_names
  ok "Coordinator: $COORDINATOR_FN"
  ok "Aggregator:  $AGGREGATOR_FN"

  # Offer to clear stale chunks before re-running
  local chunk_count
  chunk_count=$(count_s3_prefix "derived/chunks/${run_date}/")
  [[ "$chunk_count" == "None" ]] && chunk_count=0

  if [[ "$chunk_count" -gt 0 ]]; then
    step "Found $chunk_count existing chunk(s) for $run_date"
    if confirm "Clear existing chunks and manifest before re-running?"; then
      delete_s3_prefix "derived/chunks/${run_date}/"
      delete_s3_prefix "derived/manifests/${run_date}/"
      ok "Cleared old chunks and manifest"
    fi
  fi

  step "Invoking coordinator for $run_date"
  COORD_OUT="/tmp/coord-out-$$.json"
  invoke_lambda "$COORDINATOR_FN" "{\"run_date\":\"$run_date\"}" "$COORD_OUT"
  info "Response: $(cat "$COORD_OUT")"
  ok "Coordinator succeeded"

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

  step "Invoking aggregator for $run_date"
  AGG_OUT="/tmp/agg-out-$$.json"
  local agg_retry_delay=30
  for attempt in 1 2 3 4 5; do
    AGG_ERR=$(aws_cmd lambda invoke \
      --cli-binary-format raw-in-base64-out \
      --function-name "$AGGREGATOR_FN" \
      --payload "{\"run_date\":\"$run_date\"}" \
      "$AGG_OUT" 2>&1) && break
    if echo "$AGG_ERR" | grep -q "TooManyRequestsException\|Rate Exceeded"; then
      info "Rate limited, retrying in ${agg_retry_delay}s (attempt ${attempt}/5)..."
      sleep "$agg_retry_delay"
    else
      echo "$AGG_ERR" >&2
      fail "Aggregator invoke failed"
    fi
    [[ $attempt -eq 5 ]] && fail "Aggregator still rate-limited after 5 attempts"
  done
  if grep -q '"FunctionError"' "$AGG_OUT" 2>/dev/null; then
    info "Response: $(cat "$AGG_OUT")"
    fail "Aggregator returned a function error"
  fi
  info "Response: $(cat "$AGG_OUT")"
  ok "Aggregator succeeded"

  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Report regenerated for $run_date"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── Arg parsing ────────────────────────────────────────────────────────────────

usage() {
  awk '/^set -/{exit} NR>1{sub(/^# ?/,""); print}' "$0"
  exit "${1:-0}"
}

COMMAND=""
DATE_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    delete|report|regen)
      COMMAND="$1"; shift ;;
    --profile)
      AWS_PROFILE="$2"; shift 2 ;;
    --bucket)
      S3_BUCKET="$2"; shift 2 ;;
    --stack)
      CDK_STACK="$2"; shift 2 ;;
    --wait)
      WORKER_WAIT="$2"; shift 2 ;;
    --pretty)
      PRETTY=true; shift ;;
    -y|--yes)
      YES=true; shift ;;
    -h|--help)
      usage 0 ;;
    -*)
      fail "Unknown option: $1" ;;
    *)
      if [[ -z "$DATE_ARG" ]]; then
        DATE_ARG="$1"; shift
      else
        fail "Unexpected argument: $1"
      fi ;;
  esac
done

[[ -z "$COMMAND" ]] && { usage 1; }
[[ -z "$DATE_ARG" ]] && fail "Missing date argument"

case "$COMMAND" in
  delete) cmd_delete "$DATE_ARG" ;;
  report) cmd_report "$DATE_ARG" ;;
  regen)  cmd_regen  "$DATE_ARG" ;;
esac
