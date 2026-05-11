#!/usr/bin/env bash
# Backfill signal evaluation files for historical reports.
#
# Usage:
#   ./scripts/backfill-evaluations.sh [--from YYYY-MM-DD] [--to YYYY-MM-DD]
#
# Defaults:
#   --from  90 days ago
#   --to    today - 4 trading days (so exit date is at least today or earlier)
#
# The script:
#   1. Resolves the S3 bucket from CloudFormation outputs.
#   2. Calls evaluation.backfill_evaluations() for each date in the range.
#   3. Writes evaluations/YYYY-MM-DD.json for each date that has a report.
#   4. Rebuilds evaluations/compliance-summary.json at the end.
#
# Requires: AWS_PROFILE=stock-screener (or set in env)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"

# Parse args
FROM_DATE=""
TO_DATE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --from) FROM_DATE="$2"; shift 2 ;;
    --to)   TO_DATE="$2";   shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# Resolve S3 bucket from CloudFormation
echo "Resolving S3 bucket from CloudFormation..."
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name StockAnalysisInfraDev \
  --query "Stacks[0].Outputs[?OutputKey=='MarketDataBucketName'].OutputValue" \
  --output text 2>/dev/null || echo "")

if [[ -z "$BUCKET" ]]; then
  # Fallback: hardcoded bucket name from ai-steering.md
  BUCKET="stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd"
  echo "CloudFormation lookup failed — using fallback bucket: $BUCKET"
else
  echo "Bucket: $BUCKET"
fi

# Run the backfill via Python
cd "$REPO_ROOT"
python3 - <<PYEOF
import sys
import logging
import boto3
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")

sys.path.insert(0, "app")
from stock_analysis.evaluation import backfill_evaluations, nth_trading_day_before

bucket = "$BUCKET"

# Default date range
today = date.today()
from_date = "${FROM_DATE}" if "${FROM_DATE}" else (today - timedelta(days=90)).isoformat()
to_date   = "${TO_DATE}"   if "${TO_DATE}"   else nth_trading_day_before(today.isoformat(), 4)

logger.info("Backfilling evaluations: %s → %s (bucket=%s)", from_date, to_date, bucket)

s3 = boto3.client("s3")
evaluated = backfill_evaluations(s3, bucket, from_date, to_date)

logger.info("Done. %d date(s) newly evaluated.", evaluated)
PYEOF

echo ""
echo "Backfill complete. Compliance summary written to s3://$BUCKET/evaluations/compliance-summary.json"
