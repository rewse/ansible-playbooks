#!/bin/sh

readonly KEYS="Ping Download Upload"
readonly TMP_FILE=/tmp/internet.txt

for server in 7139 6492; do
  speedtest --server $server --simple > $TMP_FILE

  retval=$?

  if [ "$retval" == "0" ]; then
    break
  fi
done

if [ "$retval" != "0" ]; then
  echo $retval
  exit $retval
fi

for key in $KEYS; do
  name=`echo $key | tr A-Z a-z`
  value=`grep -i ^$key: $TMP_FILE | awk '{print $2}'`

  if [ "$value" != "" ]; then
    zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -k internet.speed[$name] -o $value > /dev/null
  fi
done

rm -f $TMP_FILE
echo 0
