#!/usr/bin/env bash

file=$1

/usr/local/bin/ssl-cert-check -c $file -n |
  grep FILE | awk '{print $6}' | sed 's/|days=//'
