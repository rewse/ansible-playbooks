#!/usr/bin/env bash

trap 'my_exit 1' 1 2 3 15

readonly tmpfile=$(mktemp --tmpdir ec2.XXXXXXXXXX)

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
# {{{ my_exit()

my_exit() {
    rm -f $tmpfile
    echo $1
    exit $1
}

# }}}
# {{{ send_instance_type()

send_instance_type() {
    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k ec2.instance_type \
        -o $(metadata instance-type) \
        > /dev/null 2>&1
}

# }}}
# {{{ obtain_ids()

obtain_ids() {
    instance_id=$(metadata instance-id)

    # Without an id the metrics below would be requested for an empty dimension,
    # which the API rejects one call at a time.
    if [ -z "$instance_id" ]; then
        my_exit 1
    fi

    aws ec2 describe-volumes \
        --region ap-northeast-1 \
        --filters Name=attachment.instance-id,Values=$instance_id \
        --query "Volumes[*].Attachments[*].[VolumeId,Device]" \
        --output text \
        > $tmpfile
}

# }}}
# {{{ send_ec2()

send_ec2() {
    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.cpu_credit_balance \
        -o $(cloudwatch -n AWS/EC2 -m CPUCreditBalance -d Name=InstanceId,Value=$instance_id -s Average) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.cpu_credit_usage \
        -o $(echo "scale=2; $(cloudwatch -n AWS/EC2 -m CPUCreditUsage -d Name=InstanceId,Value=$instance_id -s Sum) * 12" | bc 2> /dev/null) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.cpu_utilization \
        -o $(cloudwatch -n AWS/EC2 -m CPUUtilization -d Name=InstanceId,Value=$instance_id -s Average) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.network_in \
        -o $(echo "scale=2; $(cloudwatch -n AWS/EC2 -m NetworkIn -d Name=InstanceId,Value=$instance_id -s Sum) / 300" | bc 2> /dev/null) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.network_out \
        -o $(echo "scale=2; $(cloudwatch -n AWS/EC2 -m NetworkOut -d Name=InstanceId,Value=$instance_id -s Sum) / 300" | bc 2> /dev/null) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.network_packets_in \
        -o $(echo "scale=2; $(cloudwatch -n AWS/EC2 -m NetworkPacketsIn -d Name=InstanceId,Value=$instance_id -s Sum) / 300" | bc 2> /dev/null) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.network_packets_out \
        -o $(echo "scale=2; $(cloudwatch -n AWS/EC2 -m NetworkPacketsOut -d Name=InstanceId,Value=$instance_id -s Sum) / 300" | bc 2> /dev/null) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.status_check_failed \
        -o $(cloudwatch -n AWS/EC2 -m StatusCheckFailed -d Name=InstanceId,Value=$instance_id -s Maximum) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.status_check_failed_instance \
        -o $(cloudwatch -n AWS/EC2 -m StatusCheckFailed_Instance -d Name=InstanceId,Value=$instance_id -s Maximum) \
        > /dev/null 2>&1

    zabbix_sender \
        -c /etc/zabbix/zabbix_agentd.conf \
        -k cloudwatch.ec2.status_check_failed_system \
        -o $(cloudwatch -n AWS/EC2 -m StatusCheckFailed_System -d Name=InstanceId,Value=$instance_id -s Maximum) \
        > /dev/null 2>&1
}

# }}}
# {{{ send_ebs()

# BurstBalance is absent here because it belongs to gp2, where a volume earns and
# spends I/O credits. Every volume attached is gp3, whose throughput is
# provisioned rather than earned.
send_ebs() {
    for volume_id in $(awk '{print $1}' $tmpfile); do
        local device_name=$(grep $volume_id $tmpfile | awk '{print $2}' | xargs basename)

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_idle_time[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeIdleTime -d Name=VolumeId,Value=$volume_id -s Sum) / 300 * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_queue_length[$device_name] \
            -o $(cloudwatch -n AWS/EBS -m VolumeQueueLength -d Name=VolumeId,Value=$volume_id -s Average) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_read_bpop[$device_name] \
            -o $(cloudwatch -n AWS/EBS -m VolumeReadBytes -d Name=VolumeId,Value=$volume_id -s Average) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_read_bytes[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeReadBytes -d Name=VolumeId,Value=$volume_id -s Sum) / 300 * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_total_read_time[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeTotalReadTime -d Name=VolumeId,Value=$volume_id -s Average) * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_read_opts[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeReadOps -d Name=VolumeId,Value=$volume_id -s Sum) / 300 * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_write_bpop[$device_name] \
            -o $(cloudwatch -n AWS/EBS -m VolumeWriteBytes -d Name=VolumeId,Value=$volume_id -s Average) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_write_bytes[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeWriteBytes -d Name=VolumeId,Value=$volume_id -s Sum) / 300 * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_total_write_time[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeTotalWriteTime -d Name=VolumeId,Value=$volume_id -s Average) * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.volume_write_opts[$device_name] \
            -o $(echo "scale=2; $(cloudwatch -n AWS/EBS -m VolumeWriteOps -d Name=VolumeId,Value=$volume_id -s Sum) / 300 * 100" | bc 2> /dev/null) \
            > /dev/null 2>&1
    done
}

# }}}
# {{{ Main

if [ $(date +%M) -lt 5 ]; then
    send_instance_type
fi

obtain_ids
send_ec2
send_ebs
my_exit 0

# }}}