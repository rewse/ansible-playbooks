#!/usr/bin/env bash

# Collects the CloudFront and AWS WAF metrics of the cloudfront-waf stack and
# hands them to the server as trapper values.
#
# Both services publish to CloudWatch in us-east-1 whatever region the origin
# lives in. The AWS CLI spends most of a second starting and the agent allows a
# UserParameter 30 seconds, a ceiling that cannot be raised, so the script makes
# only two requests: one for the newest value of every metric, and one for the
# CloudFront totals of a closed five-minute bucket.
#
# The bucket is [B, B+300), where B is the current time rounded down to five
# minutes, less ten minutes, so CloudWatch has its complete data. Its requests
# and 5xx count are sent stamped with B. security-agent-pentest-counts on the
# origin hosts sends the AWS Security Agent pentest counts for the same bucket,
# and Zabbix subtracts them to rate the 5xx responses real clients get.

trap 'my_exit 1' 1 2 3 15

# Created only once there is a distribution to read, so an early exit leaves no
# files behind.
queryfile=
resultfile=
bucketfile=
readonly region=us-east-1
readonly stack=cloudfront-waf

# The dimensions below are what CloudWatch is expected to publish for the stack.
# Phase C of the rollout verifies them against `aws cloudwatch list-metrics`.
# WAF: the web ACL name and the rule dimension that aggregates every rule. A
# CloudFront-scoped web ACL carries no Region dimension.
readonly waf_acl=cloudfront-waf
readonly waf_rule=ALL
# CloudFront: the distribution metrics carry Region=Global.
readonly cf_region=Global

# Both services publish every minute or five minutes. The window covers two
# periods and the newest datapoint is taken, so a late arrival is still found
# while a value older than that is not sent again as if it were current.
readonly period=300
readonly window='10 minutes ago'

declare -A query_key
declare -A raw_value
queries=()

# {{{ my_exit()

my_exit() {
    rm -f "$queryfile" "$resultfile" "$bucketfile"
    echo "$1"
    exit "$1"
}

# }}}
# {{{ query_id()

# CloudWatch names a query itself and accepts only letters, digits and
# underscores, so the item key becomes one.
query_id() {
    printf 'm%s' "${1//[^a-zA-Z0-9]/_}"
}

# }}}
# {{{ add_query()

add_query() {
    local key=$1 namespace=$2 metric=$3 stat=$4 dimensions=$5
    local id

    id=$(query_id "$key")
    query_key[$id]=$key

    queries+=("$(printf \
        '{"Id":"%s","MetricStat":{"Metric":{"Namespace":"%s","MetricName":"%s","Dimensions":[%s]},"Period":%d,"Stat":"%s"}}' \
        "$id" "$namespace" "$metric" "$dimensions" "$period" "$stat")")
}

# }}}
# {{{ dimension()

dimension() {
    printf '{"Name":"%s","Value":"%s"}' "$1" "$2"
}

# }}}
# {{{ distribution_id()

# Silent on failure: the agent takes standard error as part of an item's value,
# and an empty answer is the state that means the stack is not there to read.
distribution_id() {
    aws cloudformation describe-stacks \
        --region "$region" \
        --stack-name "$stack" \
        --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" \
        --output text 2> /dev/null
}

# }}}
# {{{ plan()

plan() {
    local cf waf

    cf="$(dimension DistributionId "$1"),$(dimension Region "$cf_region")"
    waf="$(dimension WebACL "$waf_acl"),$(dimension Rule "$waf_rule")"

    add_query cloudfront.requests         AWS/CloudFront Requests        Sum     "$cf"
    add_query cloudfront.error_rate.4xx   AWS/CloudFront 4xxErrorRate    Average "$cf"
    add_query cloudfront.error_rate.5xx   AWS/CloudFront 5xxErrorRate    Average "$cf"
    add_query cloudfront.origin_latency   AWS/CloudFront OriginLatency   Average "$cf"
    # CloudWatch publishes no datapoint for a zero count, so the WAF keys are sent
    # only when there is traffic.
    add_query waf.requests.allowed        AWS/WAFV2      AllowedRequests Sum     "$waf"
    add_query waf.requests.blocked        AWS/WAFV2      BlockedRequests Sum     "$waf"
    add_query waf.requests.counted        AWS/WAFV2      CountedRequests Sum     "$waf"
}

# }}}
# {{{ fetch()

fetch() {
    local IFS=,

    printf '[%s]' "${queries[*]}" > "$queryfile"

    aws cloudwatch get-metric-data \
        --region "$region" \
        --metric-data-queries "file://$queryfile" \
        --start-time "$(date --iso-8601=seconds --date "$window")" \
        --end-time "$(date --iso-8601=seconds)" \
        --scan-by TimestampDescending \
        --query 'MetricDataResults[*].[Id,Values[0]]' \
        --output text 2> /dev/null
}

# }}}
# {{{ fetch_bucket()

# Prints the requests and the 5xx rate of the bucket starting at $2 for the
# distribution $1, one "<id> <value>" line each.
fetch_bucket() {
    local cf start=$2

    cf="$(dimension DistributionId "$1"),$(dimension Region "$cf_region")"

    printf '[%s,%s]' \
        "$(printf '{"Id":"bucket_requests","MetricStat":{"Metric":{"Namespace":"AWS/CloudFront","MetricName":"Requests","Dimensions":[%s]},"Period":%d,"Stat":"Sum"}}' "$cf" "$period")" \
        "$(printf '{"Id":"bucket_rate_5xx","MetricStat":{"Metric":{"Namespace":"AWS/CloudFront","MetricName":"5xxErrorRate","Dimensions":[%s]},"Period":%d,"Stat":"Average"}}' "$cf" "$period")" \
        > "$bucketfile"

    aws cloudwatch get-metric-data \
        --region "$region" \
        --metric-data-queries "file://$bucketfile" \
        --start-time "$(date --iso-8601=seconds --date "@$start")" \
        --end-time "$(date --iso-8601=seconds --date "@$((start + period))")" \
        --query 'MetricDataResults[*].[Id,Values[0]]' \
        --output text 2> /dev/null
}

# }}}
# {{{ send_bucket()

# Reads fetch_bucket output and sends the bucket's requests and 5xx count
# stamped with the bucket start $1. Sends nothing unless both values are
# there, so a missing datapoint is not reported as zero.
send_bucket() {
    local start=$1 id value requests='' rate=''

    while read -r id value; do
        [ "$value" = "None" ] && continue
        case $id in
            bucket_requests) requests=$value ;;
            bucket_rate_5xx) rate=$value ;;
        esac
    done

    { [ -z "$requests" ] || [ -z "$rate" ]; } && return

    awk -v start="$start" -v requests="$requests" -v rate="$rate" 'BEGIN {
        printf "- cloudfront.bucket.requests %d %.0f\n", start, requests
        printf "- cloudfront.bucket.errors.5xx %d %.0f\n", start, requests * rate / 100
    }' | zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -T -i - > /dev/null 2>&1
}

# }}}
# {{{ payload()

payload() {
    local id raw

    for id in "${!query_key[@]}"; do
        raw=${raw_value[$id]:-}
        [ -z "$raw" ] && continue

        printf -- '- %s %s\n' "${query_key[$id]}" "$raw"
    done
}

# }}}
# {{{ Main

# Fixed before any request, so a slow AWS CLI cannot move it into the next
# five minutes and make this run skip one bucket and the next send it twice.
bucket_start=$(( $(date +%s) / period * period - 2 * period ))
readonly bucket_start

distribution=$(distribution_id)

# Without a distribution there is nothing to read, and sending nothing leaves
# the items unsupported rather than reporting false values.
if [ -z "$distribution" ] || [ "$distribution" = "None" ]; then
    exit 0
fi

queryfile=$(mktemp --tmpdir cloudfront_waf.XXXXXXXXXX)
resultfile=$(mktemp --tmpdir cloudfront_waf.XXXXXXXXXX)

plan "$distribution"

fetch > "$resultfile"

while read -r id value; do
    { [ -z "$id" ] || [ "$value" = "None" ]; } && continue
    raw_value[$id]=$value
done < "$resultfile"

payload | zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -i - > /dev/null 2>&1

bucketfile=$(mktemp --tmpdir cloudfront_waf.XXXXXXXXXX)

fetch_bucket "$distribution" "$bucket_start" | send_bucket "$bucket_start"

my_exit 0

# }}}
