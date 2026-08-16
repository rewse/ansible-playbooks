#!/usr/bin/env bash

# Collects what only CloudWatch knows about this instance and its volumes, and
# hands it to the server as trapper values.
#
# Everything is asked for in one request and delivered in one. CloudWatch takes
# up to 500 queries per call and the AWS CLI spends most of a second starting, so
# a metric per call costs a second each: thirty of them ran for 27 seconds
# against the 30 the agent allows a UserParameter, which is the agent's ceiling
# and cannot be raised.

trap 'my_exit 1' 1 2 3 15

readonly queryfile=$(mktemp --tmpdir ec2.XXXXXXXXXX)
readonly resultfile=$(mktemp --tmpdir ec2.XXXXXXXXXX)
readonly region=ap-northeast-1

# EC2 and EBS publish every five minutes. The window reaches back an hour and the
# newest datapoint is taken, so a late arrival is still found.
readonly period=300
readonly window='1 hour ago'

declare -A query_key
declare -A query_mul
declare -A query_div
declare -A query_over
declare -A raw_value
queries=()

# {{{ my_exit()

my_exit() {
    rm -f $queryfile $resultfile
    echo $1
    exit $1
}

# }}}
# {{{ metadata()

# The instance answers nothing without a token, so a plain GET returns an empty
# string and every dimension built from it is rejected by the API.
metadata() {
    local token=$(curl -s -m 3 -X PUT http://169.254.169.254/latest/api/token \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60")

    curl -s -m 3 -H "X-aws-ec2-metadata-token: ${token}" \
        http://169.254.169.254/latest/meta-data/$1
}

# }}}
# {{{ query_id()

# CloudWatch names a query itself and accepts only letters, digits and
# underscores, so the item key becomes one. Deriving the name rather than
# counting lets a query name another as its denominator.
query_id() {
    printf 'm%s' "${1//[^a-zA-Z0-9]/_}"
}

# }}}
# {{{ add_query()

# The value sent is the datapoint divided by the named query, multiplied by mul
# and divided by div. A statistic summed over the period turns into a rate
# through div, and a latency needs the operation count as a denominator.
add_query() {
    local key=$1 namespace=$2 metric=$3 dimension=$4 value=$5 stat=$6
    local mul=${7:-1} div=${8:-1} over=${9:-}
    local id=$(query_id "$key")

    query_key[$id]=$key
    query_mul[$id]=$mul
    query_div[$id]=$div
    [[ -n $over ]] && query_over[$id]=$(query_id "$over")

    queries+=("$(printf \
        '{"Id":"%s","MetricStat":{"Metric":{"Namespace":"%s","MetricName":"%s","Dimensions":[{"Name":"%s","Value":"%s"}]},"Period":%d,"Stat":"%s"}}' \
        "$id" "$namespace" "$metric" "$dimension" "$value" "$period" "$stat")")
}

# }}}
# {{{ plan_ec2()

plan_ec2() {
    local d=InstanceId v=$1

    add_query cloudwatch.ec2.cpu_credit_balance           AWS/EC2 CPUCreditBalance           $d $v Average
    add_query cloudwatch.ec2.cpu_credit_usage             AWS/EC2 CPUCreditUsage             $d $v Sum     12
    add_query cloudwatch.ec2.cpu_utilization              AWS/EC2 CPUUtilization             $d $v Average
    add_query cloudwatch.ec2.network_in                   AWS/EC2 NetworkIn                  $d $v Sum      1 $period
    add_query cloudwatch.ec2.network_out                  AWS/EC2 NetworkOut                 $d $v Sum      1 $period
    add_query cloudwatch.ec2.network_packets_in           AWS/EC2 NetworkPacketsIn           $d $v Sum      1 $period
    add_query cloudwatch.ec2.network_packets_out          AWS/EC2 NetworkPacketsOut          $d $v Sum      1 $period
    add_query cloudwatch.ec2.status_check_failed          AWS/EC2 StatusCheckFailed          $d $v Maximum
    add_query cloudwatch.ec2.status_check_failed_instance AWS/EC2 StatusCheckFailed_Instance $d $v Maximum
    add_query cloudwatch.ec2.status_check_failed_system   AWS/EC2 StatusCheckFailed_System   $d $v Maximum
}

# }}}
# {{{ plan_ebs()

# BurstBalance is absent because it belongs to gp2, where a volume earns and
# spends I/O credits. Every volume attached is gp3, whose throughput is
# provisioned rather than earned.
plan_ebs() {
    local device=$1 volume=$2
    local d=VolumeId

    add_query "cloudwatch.ebs.volume_idle_time[$device]"       AWS/EBS VolumeIdleTime     $d $volume Sum   100 $period
    add_query "cloudwatch.ebs.volume_queue_length[$device]"    AWS/EBS VolumeQueueLength  $d $volume Average
    add_query "cloudwatch.ebs.volume_read_bytes[$device]"      AWS/EBS VolumeReadBytes    $d $volume Sum     1 $period
    add_query "cloudwatch.ebs.volume_read_opts[$device]"       AWS/EBS VolumeReadOps      $d $volume Sum     1 $period
    add_query "cloudwatch.ebs.volume_write_bytes[$device]"     AWS/EBS VolumeWriteBytes   $d $volume Sum     1 $period
    add_query "cloudwatch.ebs.volume_write_opts[$device]"      AWS/EBS VolumeWriteOps     $d $volume Sum     1 $period

    # Per operation rather than per period, which needs the operation count as a
    # denominator. The Average statistic does not answer this: EBS publishes at a
    # one minute granularity, so averaging over five of them gives the mean bytes
    # per minute, which reads as tens of megabytes for an operation that cannot
    # exceed 256 KiB.
    add_query "cloudwatch.ebs.volume_read_bpop[$device]"  AWS/EBS VolumeReadBytes  $d $volume Sum 1 1 \
        "cloudwatch.ebs.volume_read_opts[$device]"
    add_query "cloudwatch.ebs.volume_write_bpop[$device]" AWS/EBS VolumeWriteBytes $d $volume Sum 1 1 \
        "cloudwatch.ebs.volume_write_opts[$device]"

    # Seconds spent divided by the operations that spent them, in milliseconds.
    add_query "cloudwatch.ebs.volume_total_read_time[$device]"  AWS/EBS VolumeTotalReadTime  $d $volume Sum 1000 1 \
        "cloudwatch.ebs.volume_read_opts[$device]"
    add_query "cloudwatch.ebs.volume_total_write_time[$device]" AWS/EBS VolumeTotalWriteTime $d $volume Sum 1000 1 \
        "cloudwatch.ebs.volume_write_opts[$device]"
}

# }}}
# {{{ volumes()

# Filtered by attachment, since the call otherwise answers with every volume in
# the account, including those of other instances and those attached to nothing.
volumes() {
    aws ec2 describe-volumes \
        --region $region \
        --filters Name=attachment.instance-id,Values=$1 \
        --query "Volumes[*].Attachments[*].[VolumeId,Device]" \
        --output text 2> /dev/null
}

# }}}
# {{{ fetch()

# The agent takes standard error as part of an item's value, so a diagnostic
# printed here would arrive as the reading. Failing silently leaves the values
# unsent, which is the state that means they could not be read.
fetch() {
    local IFS=,

    printf '[%s]' "${queries[*]}" > $queryfile

    aws cloudwatch get-metric-data \
        --region $region \
        --metric-data-queries "file://$queryfile" \
        --start-time "$(date --iso-8601=seconds --date "$window")" \
        --end-time "$(date --iso-8601=seconds)" \
        --scan-by TimestampDescending \
        --query 'MetricDataResults[*].[Id,Values[0]]' \
        --output text 2> /dev/null
}

# }}}
# {{{ payload()

payload() {
    local id raw denominator

    # The instance type changes only when someone resizes the instance, and it is
    # a string where the rest are numbers.
    if [ $(date +%M) -lt 5 ]; then
        printf -- '- ec2.instance_type %s\n' "$(metadata instance-type)"
    fi

    for id in "${!query_key[@]}"; do
        raw=${raw_value[$id]:-}
        [ -z "$raw" ] && continue

        denominator=1

        if [ -n "${query_over[$id]:-}" ]; then
            denominator=${raw_value[${query_over[$id]}]:-0}

            # A volume that served no operations has no latency to report, and a
            # zero here would either divide by zero or send a value nothing
            # measured.
            [ "${denominator%%.*}" = "0" ] && continue
        fi

        printf -- '- %s %s\n' "${query_key[$id]}" \
            "$(echo "scale=4; $raw / $denominator * ${query_mul[$id]} / ${query_div[$id]}" | bc 2> /dev/null)"
    done
}

# }}}
# {{{ Main

instance_id=$(metadata instance-id)

# Without an id every metric below would be requested for an empty dimension,
# which the API rejects.
if [ -z "$instance_id" ]; then
    my_exit 1
fi

plan_ec2 $instance_id

while read -r volume device; do
    [ -z "$volume" ] && continue
    plan_ebs $(basename $device) $volume
done < <(volumes $instance_id)

fetch > $resultfile

while read -r id value; do
    [ -z "$id" -o "$value" = "None" ] && continue
    raw_value[$id]=$value
done < $resultfile

payload | zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -i - > /dev/null 2>&1

my_exit 0

# }}}
