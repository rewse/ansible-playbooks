#!/usr/bin/env bash

set -euo pipefail

export STOCK_FETCHER_DEBUG=1

code="$1"
provider="${2:-}"

LOCK_FILE="/run/zabbix/stock-price-fetcher.lock"

cd /usr/lib/zabbix/stock-price-fetcher

# Serialize execution to prevent agent-browser session conflicts
exec 9>"$LOCK_FILE"
flock 9

if [ -n "$provider" ]; then
    uv run stock-price-fetcher "$code" --source "$provider"
else
    uv run stock-price-fetcher "$code"
fi
