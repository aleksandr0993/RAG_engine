#!/usr/bin/env bash
set -euo pipefail

pip install -e .[browser]
playwright install chromium

echo "Set ENABLE_BROWSER_CAPTURE=true in .env to activate capture"
