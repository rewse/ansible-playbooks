#!/bin/sh

pathmunge /usr/local/bin

if [ "$EUID" = "0" ]; then
  pathmunge /usr/local/sbin
else
  pathmunge /usr/local/sbin after
fi

export PATH
