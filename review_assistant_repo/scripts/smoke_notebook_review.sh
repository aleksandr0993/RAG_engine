#!/usr/bin/env bash
# Smoke: POST upload (sample notebook) -> POST review -> GET review_result.
# Requires a running API (default http://127.0.0.1:8000). Run from repo root is OK if paths resolve.
set -euo pipefail

REVIEW_API_BASE="${REVIEW_API_BASE:-http://127.0.0.1:8000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SAMPLE="${ROOT}/examples/sample_notebook.ipynb"

if [[ ! -f "$SAMPLE" ]]; then
  echo "Missing sample notebook: $SAMPLE" >&2
  exit 1
fi

UPLOAD_JSON="$(curl -fsS -X POST "${REVIEW_API_BASE}/api/v1/projects/upload" -F "file=@${SAMPLE}")"
PROJECT_ID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["project_id"])' "$UPLOAD_JSON")"

curl -fsS -X POST "${REVIEW_API_BASE}/api/v1/projects/${PROJECT_ID}/review" >/dev/null
RESULT_JSON="$(curl -fsS "${REVIEW_API_BASE}/api/v1/projects/${PROJECT_ID}/review_result")"
python3 -c 'import json,sys
payload = json.loads(sys.argv[1])
assert "final_verdict" in payload and payload["final_verdict"] is not None, payload
print("OK project", sys.argv[2], "final_verdict=", payload["final_verdict"])
' "$RESULT_JSON" "$PROJECT_ID"
