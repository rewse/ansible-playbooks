#!/usr/bin/env bash

set -u
trap 'exit 1' 1 2 3 15

# {{{ sendto_zabbix()

sendto_zabbix() {
    zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -s $1 \
    -k net.wifi.$2.ch \
    -o $(iw dev wlan0 scan | grep -A 10 $3 | grep channel | awk '{print $5}') \
    > /dev/null 2>&1

    retval=$(expr $retval + $?)
}

# }}}
# {{{ Main

retval=0

sendto_zabbix victor.rewse.jp band5 74:da:88:9c:57:c1
sendto_zabbix xray-liv.rewse.jp band2 70:a7:41:a4:eb:16
sendto_zabbix xray-liv.rewse.jp band5 76:a7:41:a4:eb:17
sendto_zabbix xray-sto.rewse.jp band2 d0:21:f9:b1:b1:a9
sendto_zabbix xray-sto.rewse.jp band5 d2:21:f9:91:b1:aa

echo $retval
exit $retval

# }}}
