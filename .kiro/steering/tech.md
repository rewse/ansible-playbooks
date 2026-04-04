---
inclusion: always
---

# Technology Stack

## Core Technologies

- **Ansible**: Primary automation tool for configuration management
- **YAML**: Used for playbooks, roles, and variable definitions
- **Jinja2**: Template engine for dynamic configuration files
- **1Password CLI**: For secure storage and retrieval of sensitive information

## Common Commands

### Ansible Commands

```bash
# Run entire playbook
ansible-playbook site.yml

# Run specific playbook
ansible-playbook ubuntu.yml

# Run with specific tags
ansible-playbook ubuntu.yml --tags ubuntu,package

# Check mode (dry run)
ansible-playbook site.yml --check

# Run against specific host
ansible-playbook site.yml --limit "fox.rewse.jp"
```

### 1Password Commands

This repository uses 1Password Service Accounts for authentication. The Service Account token is configured in `.envrc` and automatically loaded by direnv.

```bash
# Verify authentication (Service Account)
op whoami

# Read secrets
op read op://ansible/database/password

# Usage example in Ansible
# In playbooks or vars files:
# db_password: "{{ lookup('pipe', 'op read op://ansible/database/password') }}"
```

**Note**: Service Accounts work in interactive shells but may fail in automated contexts due to a known 1Password CLI limitation.

## Ansible Syntax

Follow [Ansible YAML Syntax](https://docs.ansible.com/projects/ansible/latest/reference_appendices/YAMLSyntax.html).

## Best Practices

- Use tags for selective execution
- Store sensitive data in 1Password and reference with `lookup('pipe', 'op read ...')`
- Use group_vars when saving share configuration
- Verify with `--check` before applying changes
- Keep role-specific variables in `role/vars` directories
- Don't add temporary or one-time fixes to playbooks; apply them directly via SSH instead
