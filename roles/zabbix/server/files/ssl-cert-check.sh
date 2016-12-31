#!/bin/sh

server=$1
port=$2

/usr/local/bin/ssl-cert-check -s $server -p $port -n |
  awk '{print $6}' | sed 's/|days=//'
