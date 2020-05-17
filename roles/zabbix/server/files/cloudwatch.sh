#!/usr/bin/env bash

trap 'exit 1' 1 2 3 15

show_usage() {
  cat <<! >&2
<USAGE> cloudwatch.sh -n <NAMESPACE> -m <METRIC> -d <DIMENSIONS> -s <STATISTICS> [-D <DIVISOR>]

Example: cloudwatch.sh -n AWS/EC2 -m CPUUtilization -d Name=InstanceId,Value=i-12345678901234567 -s Average
!

  exit 1
}

while getopts n:d:m:s:D: OPT
do
  case $OPT in
    n) namespace=$OPTARG ;;
    m) metric=$OPTARG ;;
    d) dimensions=$OPTARG ;;
    s) statistics=$OPTARG ;;
    D) divisor=$OPTARG ;;
    *) show_usage ;;
  esac
done

if [ "$namespace" == "" -o "$metric" == "" -o "$dimensions" == "" -o "$statistics" == "" ]; then
  show_usage
fi

value=$(cloudwatch -n $namespace -m $metric -d $dimensions -s $statistics)

if [ "$divisor" != "" ]; then
  echo "scale=2; $value / $divisor" | bc
else
  echo $value
fi
