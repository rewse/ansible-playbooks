#!/usr/bin/env bash

trap 'my_exit 1' 1 2 3 15

readonly ble_mac=$1
readonly tmpfile=$(mktemp --tmpdir switchbot_meter.XXXXXXXXXX)

if [ ! "$ble_mac" ]; then
    echo "[USAGE] switchbot.sh <ble_mac>"
    exit 1
fi

# {{{ my_exit()

my_exit() {
    rm -f $tmpfile
    echo $1
    exit $1
}

# }}}
# {{{ send_humiture()

send_humiture() {
    /usr/local/sbin/switchbot_meter $ble_mac Humiture > $tmpfile

    retval=$?

    if [ "$retval" != "0" ]; then
        my_exit $retval
    fi

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.temp[$ble_mac] \
        -o $(cat $tmpfile | grep $ble_mac | awk '{print $2}' | sed "s/'C//") \
    > /dev/null 2>&1

    retval=$?

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.humi[$ble_mac] \
        -o $(cat $tmpfile | grep $ble_mac | awk '{print $3}' | sed "s/%//") \
    > /dev/null 2>&1

    retval=$(expr $retval + $?)
}

# }}}
# {{{ Main

send_humiture

my_exit $retval

# }}}
