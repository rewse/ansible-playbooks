#!/bin/sh

hostname=$1

tmpfile=/tmp/apache.html

trap 'my_exit 1' 1 2 3 15

my_exit() {
  rm -f $tmpfile
  echo $1
  exit $1
}

curl -so $tmpfile http://$hostname/server-status

retval=$?

if [ $retval != "0" ]; then
  my_exit $retval
fi

working_processes=`grep 'requests currently being processed' $tmpfile | awk '{print $1}' | sed 's/<dt>//'`
idle_processes=`grep 'requests currently being processed' $tmpfile | awk '{print $6}'`
reqps=`grep 'requests/sec' $tmpfile | awk '{print $1}' | sed 's/<dt>//'`
byteps=`grep 'B/second' $tmpfile | awk '{print $4}'`

zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -k apache.proc.num[working] -o $working_processes > /dev/null
zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -k apache.proc.num[idle] -o $idle_processes > /dev/null
zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -k apache.perf[reqps] -o $reqps > /dev/null
zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -k apache.perf[byteps] -o $byteps > /dev/null

my_exit 0
