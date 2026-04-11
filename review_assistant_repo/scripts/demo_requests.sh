#!/usr/bin/env bash
set -euo pipefail

UPLOAD_RESPONSE=$(curl -s -X POST http://127.0.0.1:8000/api/v1/projects/upload -F "file=@examples/sample_notebook.ipynb")
echo "$UPLOAD_RESPONSE"
PROJECT_ID=$(python - <<'PY'
import json,sys
print(json.loads(sys.stdin.read())["project_id"])
PY
<<< "$UPLOAD_RESPONSE")

curl -s -X POST http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/review | jq
curl -s http://127.0.0.1:8000/api/v1/projects/${PROJECT_ID}/review_result | jq
