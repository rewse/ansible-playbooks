#!/bin/sh

server=$1
port=$2

/usr/local/bin/ssl-cert-check -s $server -p $port -n |
  sed 's/  */ /g' | cut -f6 -d" "
