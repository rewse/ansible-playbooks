#!/bin/bash

trap 'my_exit 1' 1 2 3 15

BLE_MAC=$1
RES_FILE=$(mktemp --tmpdir switchbot_meter.XXXXXXXXXX)

# {{{ my_exit()

my_exit() {
    rm -f $RES_FILE
    echo $1
    exit $1
}

# }}}
# {{{ send_humiture()

send_humiture() {
    /usr/local/sbin/switchbot_meter $BLE_MAC Humiture > $RES_FILE

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.temp[$BLE_MAC] \
        -o $(cat $RES_FILE | grep $BLE_MAC | awk '{print $2}' | sed "s/'C//") \
    > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k switchbot.meter.humi[$BLE_MAC] \
        -o $(cat $RES_FILE | grep $BLE_MAC | awk '{print $3}' | sed "s/%//") \
    > /dev/null 2>&1

    rm -f $RES_FILE
}

# }}}
# {{{ Main

send_humiture

my_exit 0

# }}}
