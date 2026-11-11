#!/usr/bin/env bash

trap 'my_exit 1' 1 2 3 15

readonly hostname=$1
tmpfile=$(mktemp --tmpdir apache-server-status.XXXXXXXXXX)
readonly tmpfile

if [ ! "$hostname" ]; then
    echo "[USAGE] apache.sh <hostname>"
    exit 1
fi

# {{{ my_exit

my_exit() {
    rm -f "$tmpfile"
    echo "$1"
    exit "$1"
}

# }}}
# {{{ status_value

# Prints the numeric value of a key in the machine-readable status. The key
# must start the line, so text that clients control cannot supply it. Apache
# omits the leading zero of fractions (".733"), which is restored here.
status_value() {
    awk -v key="$1" '
        index($0, key ": ") == 1 {
            value = substr($0, length(key) + 3)
            if (value ~ /^[0-9.]+([eE][-+]?[0-9]+)?$/) {
                sub(/^\./, "0.", value)
                print value
            }
            exit
        }
    ' "$tmpfile"
}

# }}}
# {{{ send_value

# Sends nothing when the status lacks the value, so Zabbix marks the item
# unsupported instead of storing false data.
send_value() {
    if [ -n "$2" ]; then
        zabbix_sender -c /etc/zabbix/zabbix_agentd.conf \
            -k "$1" \
            -o "$2" > /dev/null 2>&1
    fi
}

# }}}
# {{{ send_server_status

send_server_status() {
    curl -so "$tmpfile" "https://$hostname/server-status?auto"

    retval=$?

    if [ "$retval" != "0" ]; then
        my_exit $retval
    fi

    send_value 'apache.proc.num[working]' "$(status_value BusyWorkers)"
    send_value 'apache.proc.num[idle]' "$(status_value IdleWorkers)"
    send_value 'apache.perf[reqps]' "$(status_value ReqPerSec)"
    # BytesPerSec is in bytes, matching the B/s unit of the item.
    send_value 'apache.perf[byteps]' "$(status_value BytesPerSec)"
}

# }}}
# {{{ Main

send_server_status

my_exit 0
