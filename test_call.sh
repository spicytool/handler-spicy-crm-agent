#!/usr/bin/env bash
# Quick script to test handler response time against deployed Cloud Run.
# Usage:
#   ./test_call.sh                          # default message
#   ./test_call.sh "custom message"         # custom message
#
# Requires WEBHOOK_SECRET env var (or set it below).

set -euo pipefail

SERVICE_URL="https://handler-spicy-crm-agent-dq2rcioihq-uc.a.run.app"
MESSAGE="${1:-Hola, quiero ver mis contactos}"
WEBHOOK_SECRET="${WEBHOOK_SECRET:?Set WEBHOOK_SECRET env var}"

PAYLOAD=$(cat <<EOF
{
  "companyId": "test-company",
  "userId": "test-user",
  "message": "$MESSAGE",
  "userEmail": "test@spicytool.com"
}
EOF
)

echo "--- Handler Test ---"
echo "URL:     $SERVICE_URL"
echo "Message: $MESSAGE"
echo ""

echo ">>> Webhook response:"
time curl -s -w "\n\nHTTP Status: %{http_code}\nTime Total:  %{time_total}s\nTime TTFB:   %{time_starttransfer}s\n" \
  -X POST "${SERVICE_URL}/webhook" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${WEBHOOK_SECRET}" \
  -d "$PAYLOAD"
