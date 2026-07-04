#!/usr/bin/env bash

set -euo pipefail

export STOCK_FETCHER_DEBUG=1

code="$1"
provider="${2:-}"

cd /usr/lib/zabbix/stock-price-fetcher

if [ -n "$provider" ]; then
    uv run stock-price-fetcher "$code" --source "$provider"
else
    uv run stock-price-fetcher "$code"
fi
