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

```bash
# Sign in to 1Password
op signin

# Check authentication status
op whoami

# Read secrets (for testing)
op read op://ansible/database/password

# Usage example in Ansible
# In playbooks or vars files:
# db_password: "{{ lookup('pipe', 'op read op://ansible/database/password') }}"
```

## Ansible Syntax

You MSUT follow [Ansible YAML Syntax](https://docs.ansible.com/projects/ansible/latest/reference_appendices/YAMLSyntax.html).

## Best Practices

- You SHOULD use tags for selective execution
- You MUST store sensitive data in 1Password and reference with `lookup('pipe', 'op read ...')`
- When saving share configuration, you SHOULD use group_vars
- Before applying changes, you SHOUL verify with `--check`
- You MUST keep role-specific variables in `role/vars` directories
