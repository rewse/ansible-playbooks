#!/usr/bin/env bash

code=$1
provider=$2

if [ "$provider" == "msn" ]; then
    /usr/local/bin/market-price-check -p $provider $code
else
    /usr/local/bin/market-price-check $code
fi