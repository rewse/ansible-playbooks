#!/usr/bin/env bash

set -u
trap 'exit 1' 1 2 3 15

readonly tmpfile=$(mktemp --tmpdir speed-cloudflare.XXXXXXXXXX)

# {{{ my_exit()

my_exit() {
    rm -f $tmpfile
    echo $1
    exit $1
}

# }}}
# {{{ Main

retval=0

npx speed-cloudflare-cli > $tmpfile

retval=$(expr $retval + $?)

sed -i 's/\x1b\[[0-9;]*m//g' $tmpfile

zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -s $(hostname) \
    -k net.internet.latency \
    -o $(grep Latency $tmpfile | awk '{print $2}')
    > /dev/null 2>&1

retval=$(expr $retval + $?)

zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -s $(hostname) \
    -k net.internet.jitter \
    -o $(grep Jitter $tmpfile | awk '{print $2}')
    > /dev/null 2>&1

retval=$(expr $retval + $?)

zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -s $(hostname) \
    -k net.internet.download \
    -o $(grep Download $tmpfile | awk '{print $3}')
    > /dev/null 2>&1

retval=$(expr $retval + $?)

zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -s $(hostname) \
    -k net.internet.upload \
    -o $(grep Upload $tmpfile | awk '{print $3}')
    > /dev/null 2>&1

retval=$(expr $retval + $?)

my_exit $retval

# }}}
