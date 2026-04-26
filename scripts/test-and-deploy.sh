#!/usr/bin/env bash
# Runs the full test suite then deploys infra + web assets.
# Usage:
#   ./scripts/test-and-deploy.sh            # tests + full deploy
#   ./scripts/test-and-deploy.sh --test-only # tests only, no deploy
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ONLY=false
[[ "${1:-}" == "--test-only" ]] && TEST_ONLY=true

AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
AWS_REGION="us-west-2"
CDK_ACCOUNT="841425310647"
CDK_REGION="us-west-2"
S3_BUCKET="stockanalysisinfradev-marketdatabucket61df0c4c-esoqnk197msd"
CF_DISTRIBUTION="E2IOLFNFUVHVKE"
CDK_STACK="StockAnalysisInfraDev"

step() { echo; echo "▶ $*"; }
ok()   { echo "  ✓ $*"; }
fail() { echo; echo "✗ $*" >&2; exit 1; }

# ── Tests ──────────────────────────────────────────────────────────────────────

step "Python tests (pytest)"
cd "$REPO_ROOT"
python3 -m pytest --tb=short -q || fail "Python tests failed"
ok "pytest passed"

step "CDK unit tests (Jest)"
cd "$REPO_ROOT/infra"
npm test || fail "CDK Jest tests failed"
ok "CDK tests passed"

step "Web unit tests (node:test)"
cd "$REPO_ROOT/web"
npm test || fail "Web tests failed"
ok "Web tests passed"

if $TEST_ONLY; then
  echo
  echo "All tests passed. Skipping deploy (--test-only)."
  exit 0
fi

# ── Deploy ─────────────────────────────────────────────────────────────────────

step "CDK build"
cd "$REPO_ROOT/infra"
npm run build || fail "CDK build failed"
ok "CDK build succeeded"

step "CDK deploy ($CDK_STACK)"
AWS_PROFILE="$AWS_PROFILE" \
  CDK_DEFAULT_ACCOUNT="$CDK_ACCOUNT" \
  CDK_DEFAULT_REGION="$CDK_REGION" \
  npx cdk deploy "$CDK_STACK" --require-approval never || fail "CDK deploy failed"
ok "CDK deploy succeeded"

step "Sync web assets → S3"
cd "$REPO_ROOT"
AWS_PROFILE="$AWS_PROFILE" aws s3 sync web \
  "s3://$S3_BUCKET" \
  --region "$AWS_REGION" \
  --exclude 'node_modules/*' \
  --exclude 'tests/*' \
  --exclude 'scripts/*' || fail "S3 sync failed"
ok "S3 sync succeeded"

step "Invalidate CloudFront cache"
AWS_PROFILE="$AWS_PROFILE" aws cloudfront create-invalidation \
  --region "$AWS_REGION" \
  --distribution-id "$CF_DISTRIBUTION" \
  --paths '/*' \
  --query 'Invalidation.Id' \
  --output text || fail "CloudFront invalidation failed"
ok "CloudFront invalidation triggered"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deploy complete."
echo "  https://d2r08g384yeqpo.cloudfront.net"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
