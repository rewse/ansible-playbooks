#!/bin/bash

trap 'my_exit 1' 1 2 3 15

readonly ble_mac=$1
readonly res_file=$(mktemp --tmpdir switchbot_meter.XXXXXXXXXX)

# {{{ my_exit()

my_exit() {
    rm -f $res_file
    echo $1
    exit $1
}

# }}}
# {{{ send_humiture()

send_humiture() {
    /usr/local/sbin/switchbot_meter $ble_mac Humiture > $res_file

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.temp[$ble_mac] \
        -o $(cat $res_file | grep $ble_mac | awk '{print $2}' | sed "s/'C//") \
    > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.humi[$ble_mac] \
        -o $(cat $res_file | grep $ble_mac | awk '{print $3}' | sed "s/%//") \
    > /dev/null 2>&1
}

# }}}
# {{{ Main

send_humiture

my_exit 0

# }}}
