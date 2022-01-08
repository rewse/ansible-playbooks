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
sendto_zabbix xray-liv.rewse.jp band2 9c:c9:eb:da:1d:01
sendto_zabbix xray-liv.rewse.jp band5 9c:c9:eb:da:1d:11
sendto_zabbix xray-sto.rewse.jp band2 44:a5:6e:5b:83:81
sendto_zabbix xray-sto.rewse.jp band5 44:a5:6e:5b:83:91

echo $retval
exit $retval

# }}}
