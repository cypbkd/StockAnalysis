#!/usr/bin/env bash
# Manage the Gemini API key stored in AWS Secrets Manager.
#
# Usage:
#   scripts/manage-gemini-key.sh set "AIza..."   # Create or update the key
#   scripts/manage-gemini-key.sh rotate "AIza..." # Alias for set (creates new version)
#   scripts/manage-gemini-key.sh get              # Show the first 12 chars (safe to read)
#   scripts/manage-gemini-key.sh delete           # Schedule deletion (30-day recovery window)
#
# The secret is stored in AWS Secrets Manager as a plain string.
# The aggregator Lambda reads it at runtime via the GEMINI_SECRET_NAME env var.
set -euo pipefail

SECRET_NAME="stock-analysis/gemini-api-key"
AWS_PROFILE="${AWS_PROFILE:-stock-screener}"
AWS_REGION="us-west-2"

_aws() {
  AWS_PROFILE="$AWS_PROFILE" aws --region "$AWS_REGION" "$@"
}

_secret_exists() {
  _aws secretsmanager describe-secret --secret-id "$SECRET_NAME" &>/dev/null
}

case "${1:-}" in

  set|rotate)
    KEY="${2:-}"
    if [[ -z "$KEY" ]]; then
      echo "Usage: $0 set <api-key>" >&2
      exit 1
    fi
    if _secret_exists; then
      _aws secretsmanager put-secret-value \
        --secret-id "$SECRET_NAME" \
        --secret-string "$KEY"
      echo "✓ Secret updated: $SECRET_NAME"
    else
      _aws secretsmanager create-secret \
        --name "$SECRET_NAME" \
        --description "Gemini API key for nightly news summarization in the aggregator Lambda" \
        --secret-string "$KEY"
      echo "✓ Secret created: $SECRET_NAME"
    fi
    ;;

  get)
    RAW=$(_aws secretsmanager get-secret-value \
      --secret-id "$SECRET_NAME" \
      --query "SecretString" \
      --output text)
    echo "Key prefix: ${RAW:0:12}..."
    ;;

  delete)
    echo "Scheduling deletion of '$SECRET_NAME' (30-day recovery window)..."
    _aws secretsmanager delete-secret \
      --secret-id "$SECRET_NAME" \
      --recovery-window-in-days 30
    echo "✓ Deletion scheduled. Restore within 30 days with: aws secretsmanager restore-secret --secret-id $SECRET_NAME"
    ;;

  *)
    echo "Usage: $0 {set|rotate|get|delete} [api-key]" >&2
    exit 1
    ;;

esac
