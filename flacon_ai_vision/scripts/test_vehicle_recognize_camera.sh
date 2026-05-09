#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5003}"
USERNAME="${USERNAME:-admin}"
PASSWORD="${PASSWORD:-admin123}"
CAMERA_ID="${CAMERA_ID:-1}"
ZONE_ID="${ZONE_ID:-}"
PERSIST="${PERSIST:-true}"
SAVE_SNAPSHOT="${SAVE_SNAPSHOT:-true}"
TOKEN="${TOKEN:-}"

echo "========================================================================"
echo "1) Health check -> ${BASE_URL}/health"
echo "========================================================================"
curl -fsS "${BASE_URL}/health"
echo

if [[ -z "${TOKEN}" ]]; then
  echo "========================================================================"
  echo "2) Login -> ${BASE_URL}/api/auth/login"
  echo "========================================================================"
  LOGIN_JSON="$(curl -fsS -X POST "${BASE_URL}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}")"
  TOKEN="$(python - <<'PY' "${LOGIN_JSON}"
import json, sys
data = json.loads(sys.argv[1])
print(data.get("access_token", ""))
PY
)"
  if [[ -z "${TOKEN}" ]]; then
    echo "ERROR: Login succeeded but access_token missing."
    exit 1
  fi
  echo "Token received (first 30 chars): ${TOKEN:0:30}..."
else
  echo "========================================================================"
  echo "2) Using provided token"
  echo "========================================================================"
  echo "Token provided (first 30 chars): ${TOKEN:0:30}..."
fi

PAYLOAD="{\"persist\":${PERSIST},\"save_snapshot\":${SAVE_SNAPSHOT}"
if [[ -n "${ZONE_ID}" ]]; then
  PAYLOAD="${PAYLOAD},\"zone_id\":${ZONE_ID}"
fi
PAYLOAD="${PAYLOAD}}"

echo "========================================================================"
echo "3) Recognize from camera -> ${BASE_URL}/api/vehicle/recognize/camera/${CAMERA_ID}"
echo "========================================================================"
RESPONSE="$(curl -fsS -X POST "${BASE_URL}/api/vehicle/recognize/camera/${CAMERA_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")"

echo "========================================================================"
echo "4) Full JSON response"
echo "========================================================================"
echo "${RESPONSE}"

echo "========================================================================"
echo "5) Key fields"
echo "========================================================================"
python - <<'PY' "${RESPONSE}"
import json, sys
data = json.loads(sys.argv[1])
keys = [
    "success", "status", "vehicle_detected", "plate_number", "plate_type",
    "confidence", "priority", "event_id", "snapshot_path", "camera_id",
    "zone_id", "timestamp", "reason", "security_tag"
]
print(json.dumps({k: data.get(k) for k in keys}, indent=2, ensure_ascii=False))
PY

