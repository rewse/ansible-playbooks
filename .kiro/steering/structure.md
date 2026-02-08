---
inclusion: always
---

# Project Structure

## Top-Level Organization

- **Playbooks**: Root-level YAML files (e.g., `site.yml`, `ubuntu.yml`, `ec2.yml`)
- **Inventory**: Host definitions in `hosts` file
- **Configuration**: Ansible configuration in `ansible.cfg`
- **Group Variables**: Stored in `group_vars/` directory
- **Roles**: Modular components in `roles/` directory

## Playbook Structure

Playbooks follow a consistent pattern:
- Define target hosts
- Set common parameters (become, remote_user)
- Apply relevant roles

Example:
```yaml
---
- hosts: ubuntu
  become: yes
  remote_user: ubuntu
  tags: [ubuntu]
  roles:
    - ubuntu
    - postfix/client
    - dotfiles/linux
```

Task example:
```yaml
- name: "ntp : Configure NTP servers"
  ansible.builtin.lineinfile:
    path: /etc/systemd/timesyncd.conf
    regexp: '^#?NTP='
    line: 'NTP=ntp.nict.jp ntp.jst.mfeed.ad.jp'
  notify: "systemd-timesyncd: Restart"
  tags:
    - raspberrypi
    - config
    - time
    - raspberrypi_ntp
    - raspberrypi_ntp_config
```

## Role Structure

Each role follows standard Ansible directory structure:
- `tasks/`: main.yml containing role tasks
- `handlers/`: Event handlers triggered by tasks
- `templates/`: Jinja2 templates (*.j2)
- `files/`: Static files to copy to hosts
- `vars/`: Role-specific variables
- `meta/`: Role dependencies and metadata

## Variable Hierarchy

1. **Group Variables**: `group_vars/group_name/vars`
2. **Role Variables**: `roles/role_name/vars/main.yml`
3. **Host Variables**: Defined in inventory or separate files

## Naming Conventions

- **Files**: Use lowercase with underscores or hyphens
- **Variables**: Use snake_case (lowercase with underscores)
- **Roles**: Use lowercase descriptive names reflecting their purpose
- **Submodules**: Use lowercase names (e.g., `ntp`, `swap`, `ssh`)
- **Task Names**: Format as `"{submodule} : {Description}"` where:
  - Submodule name is lowercase
  - Description starts with uppercase letter
  - Example: `"ntp : Configure NTP servers"`, `"ec2 : Install packages"`
- **Tags**: All lowercase (e.g., `raspberrypi`, `config`, `raspberrypi_ntp_config`)
- **Common Tag Categories**: `install`, `config`, `update`, `init`

### Tag Structure

Tags should follow a hierarchical pattern for flexible filtering:
1. **Role name**: Base role identifier (e.g., `raspberrypi`)
2. **Category**: Action type (e.g., `install`, `config`, `init`, `update`)
3. **Submodule**: Specific component being configured (e.g., `ntp`, `swap`, `ssh`)
4. **Combined tags**: For precise targeting
   - `{role}_{submodule}` (e.g., `raspberrypi_ntp`)
   - `{role}_{submodule}_{category}` (e.g., `raspberrypi_ntp_config`)

Example tag set:
```yaml
tags:
  - raspberrypi          # Role level
  - config               # Category level
  - ntp                  # Submodule level
  - raspberrypi_ntp      # Role + submodule
  - raspberrypi_ntp_config  # Role + submodule + category
```

## Best Practices

- You MUST organize related roles in subdirectories (e.g., `zabbix/agent/ubuntu`)
- You SHOULD use tags consistently for selective execution
- You MUST write tags in YAML list format with proper indentation
- You MUST focus roles on single responsibility
- You SHOULD leverage handlers for service restarts and other triggered actions
- You SHOULD use templates for dynamic configuration files
- YOu MUST store sensitive data in 1Password
