---
inclusion: always
---

# Ansible Conventions

## Roles and Tasks

- Place related roles in nested directories when the hierarchy is meaningful, such as `zabbix/agent/ubuntu`.
- Name tasks `"{submodule} : {Description}"`; keep the submodule lowercase and start the description with a capital letter.
- Store role-specific variables in `roles/<role>/vars/main.yml` and shared inventory values in `group_vars/<group>/vars`.

## Tags

- Write tags as an indented YAML list.
- Include the applicable role, operation (`init`, `install`, `config`, or `update`), component, and composite tags such as `{role}_{component}` and `{role}_{component}_{operation}`.
- Make every advertised granular tag independently runnable by including its prerequisite directory, checkout, and configuration tasks.

```yaml
tags:
  - raspberrypi
  - config
  - ntp
  - raspberrypi_ntp
  - raspberrypi_ntp_config
```

## Idempotency

- Notify restart handlers only when managed content changes.
- Keep check mode non-mutating. If a dry-run checkout does not create the source needed by a deployment task, skip that deployment and report why.
