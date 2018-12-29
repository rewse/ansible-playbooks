#!/bin/sh

file=$1

/usr/local/bin/ssl-cert-check -c $file -p $port -n |
  awk '{print $6}' | sed 's/|days=//'
