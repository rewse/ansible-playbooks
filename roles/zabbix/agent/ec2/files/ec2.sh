#!/usr/bin/env bash

trap 'my_exit 1' 1 2 3 15

readonly tmpfile=$(mktemp --tmpdir ec2.XXXXXXXXXX)

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
        -o $(GET http://169.254.169.254/latest/meta-data/instance-type) \
        > /dev/null 2>&1
}

# }}}
# {{{ obtain_ids()

obtain_ids() {
    instance_id=$(GET http://169.254.169.254/latest/meta-data/instance-id)

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

send_ebs() {
    for volume_id in $(awk '{print $1}' $tmpfile); do
        local device_name=$(grep $volume_id $tmpfile | awk '{print $2}' | xargs basename)

        zabbix_sender \
            -c /etc/zabbix/zabbix_agentd.conf \
            -k cloudwatch.ebs.burst_balance[$device_name] \
            -o $(cloudwatch -n AWS/EBS -m BurstBalance -d Name=VolumeId,Value=$volume_id -s Average) \
            > /dev/null 2>&1

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