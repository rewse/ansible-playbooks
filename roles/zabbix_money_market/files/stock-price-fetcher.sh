#!/usr/bin/env bash

set -euo pipefail

export STOCK_FETCHER_DEBUG=1

code="$1"
provider="${2:-}"

LOCK_FILE="/run/zabbix/stock-price-fetcher.lock"

cd /opt/stock-price-fetcher

# agent-browser looks up chromium on PATH; the browser component links it to
# the newest Playwright build. AGENT_BROWSER_EXECUTABLE_PATH would also replace
# the Lightpanda binary that the Yahoo source uses.
export PATH="/var/lib/zabbix/.local/bin:$PATH"

# Serialize execution to prevent agent-browser session conflicts
exec 9>"$LOCK_FILE"
flock 9

if [ -n "$provider" ]; then
    uv run --frozen stock-price-fetcher "$code" --source "$provider"
else
    uv run --frozen stock-price-fetcher "$code"
fi
