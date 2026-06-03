#!/usr/bin/env bash
# Upload a probe-run evidence pack to Sectum Cloud's /evidence/upload.
#
# The Snapshot tier ships the OSS `sectum` CLI as the probe runner; this
# script is the missing piece: it takes a completed run's evidence pack
# (the three files produced by `sectum-ai report`) and POSTs them to the
# Sectum Cloud delivery API. Sectum Cloud then writes the pack to its
# S3 bucket and emails the customer + the operator a download link.
#
# Wire this into cron to make a Snapshot subscription self-running. The
# 10-line CI / cron contract looks like:
#
#   sectum-ai seed   --workdir .sectum-ai --config /etc/sectum-ai/sectum-ai.yaml
#   sectum-ai probe  --workdir .sectum-ai --config /etc/sectum-ai/sectum-ai.yaml --output json
#   sectum-ai report --workdir .sectum-ai --config /etc/sectum-ai/sectum-ai.yaml
#   ./upload-evidence-pack.sh \
#     --workdir .sectum-ai \
#     --customer-id "$SECTUM_CUSTOMER_ID" \
#     --customer-email "$SECTUM_CUSTOMER_EMAIL" \
#     --api-url "https://platform.sectum.ai/evidence/upload"
#
# The bearer secret is read from $SECTUM_UPLOAD_BEARER (env). Sectum
# Cloud issues this once at subscription time; rotate by re-fetching
# from the customer dashboard.
#
# Usage:
#   ./upload-evidence-pack.sh [--workdir DIR] --customer-id ID \
#       --customer-email EMAIL [--engagement-id ULID] [--api-url URL]
#
# Defaults:
#   --workdir       .sectum-ai
#   --engagement-id auto-generated ULID (time-sortable; the operator can
#                                       reproduce the order in
#                                       internal/engagements/<id>.md)
#   --api-url       https://platform.sectum.ai/evidence/upload

set -euo pipefail

workdir=".sectum-ai"
customer_id=""
customer_email=""
engagement_id=""
api_url="https://platform.sectum.ai/evidence/upload"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)         workdir="$2"; shift 2;;
    --customer-id)     customer_id="$2"; shift 2;;
    --customer-email)  customer_email="$2"; shift 2;;
    --engagement-id)   engagement_id="$2"; shift 2;;
    --api-url)         api_url="$2"; shift 2;;
    *) echo "unknown flag: $1" >&2; exit 64;;
  esac
done

if [[ -z "$customer_id" || -z "$customer_email" ]]; then
  echo "--customer-id and --customer-email are required" >&2
  exit 64
fi

if [[ -z "${SECTUM_UPLOAD_BEARER:-}" ]]; then
  echo "SECTUM_UPLOAD_BEARER env var is not set (Sectum Cloud issues this at subscription time)" >&2
  exit 64
fi

# Required pack files.
evidence_json="$workdir/evidence.json"
audit_pack_pdf="$workdir/audit-pack.pdf"
intoto_json="$workdir/attestation.intoto.json"

for f in "$evidence_json" "$audit_pack_pdf" "$intoto_json"; do
  if [[ ! -f "$f" ]]; then
    echo "missing $f (did 'sectum-ai report' run successfully?)" >&2
    exit 65
  fi
done

# Auto-generate an engagement ID if the caller did not pass one. ULIDs
# are 26 chars of Crockford base32; the first 10 encode the timestamp
# so engagement IDs sort chronologically. python3 is required (ships
# with most CI runners; install python3 if absent).
if [[ -z "$engagement_id" ]]; then
  engagement_id=$(python3 -c '
import secrets, time
alpha = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
t = int(time.time() * 1000)
ts = "".join(alpha[(t >> (45 - i * 5)) & 31] for i in range(10))
rand = "".join(alpha[secrets.randbelow(32)] for _ in range(16))
print(ts + rand)
  ')
fi

echo "Uploading evidence pack:"
echo "  customer_id:    $customer_id"
echo "  engagement_id:  $engagement_id"
echo "  customer_email: $customer_email"
echo "  api_url:        $api_url"

# Optional pack files. Only attach if present.
optional_args=()
if [[ -f "$workdir/rekor-proof.json" ]]; then
  optional_args+=(-F "rekor-proof.json=@$workdir/rekor-proof.json")
fi
if [[ -f "$workdir/tsa-token.tsr" ]]; then
  optional_args+=(-F "tsa-token=@$workdir/tsa-token.tsr")
fi

response=$(mktemp)
http_code=$(curl -sS -o "$response" -w "%{http_code}" \
  -X POST "$api_url" \
  -H "Authorization: Bearer $SECTUM_UPLOAD_BEARER" \
  -F "customer_id=$customer_id" \
  -F "engagement_id=$engagement_id" \
  -F "customer_email=$customer_email" \
  -F "evidence.json=@$evidence_json" \
  -F "audit-pack.pdf=@$audit_pack_pdf" \
  -F "attestation.intoto.json=@$intoto_json" \
  "${optional_args[@]}")

if [[ "$http_code" != "200" ]]; then
  echo "upload failed (HTTP $http_code):" >&2
  cat "$response" >&2
  echo >&2
  exit 1
fi

echo "upload succeeded:"
cat "$response"
echo
