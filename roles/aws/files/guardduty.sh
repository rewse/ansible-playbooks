#!/bin/bash

trap 'my_exit 1' 1 2 3 15

# {{{ my_exit()

my_exit() {
  echo $1
  exit $1
}

# }}}
# {{{ send_num_findings()

send_num_findings() {
  zabbix_sender \
    -c /etc/zabbix/zabbix_agentd.conf \
    -k guardduty.findings.num \
    -o $(aws guardduty list-findings \
      --region ap-northeast-1 \
      --output text \
      --detector-id=$(aws guardduty list-detectors \
        --region ap-northeast-1 \
        --query "DetectorIds[*]" \
        --output text \
      ) | wc -l \
    ) \
    > /dev/null 2>&1
}

# }}}
# {{{ Main

send_num_findings
my_exit 0

# }}}
