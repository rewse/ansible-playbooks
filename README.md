# Ansible Infrastructure Management

This repository contains Ansible playbooks and roles for managing infrastructure components across multiple environments.

## Target Environments

- **Ubuntu Servers**: Production and staging environments
- **AWS EC2**: Cloud instances
- **Raspberry Pi**: IoT and home automation devices
- **macOS**: Developer workstations (business and personal)

## Project Structure

```
.
├── ansible.cfg           # Ansible configuration file
├── hosts                 # Inventory file
├── site.yml              # Main playbook
├── ubuntu.yml            # Playbook for Ubuntu servers
├── ec2.yml               # Playbook for EC2 instances
├── raspberrypi.yml       # Playbook for Raspberry Pi
├── darwin-business.yml   # Playbook for macOS business
├── darwin-personal.yml   # Playbook for macOS personal
├── group_vars/           # Group variables
│   ├── all/              # Variables common to all hosts
│   ├── singleton_ext1/   # External singleton host variables
│   ├── singleton_int1/   # Internal singleton host 1 variables
│   └── singleton_int2/   # Internal singleton host 2 variables
└── roles/                # Ansible roles (services, applications, configuration management)
```

## Usage

### Prerequisites

- Ansible 2.10 or later installed
- SSH access configured to target hosts
- 1Password CLI (`op`) installed and authenticated

### Basic Commands

#### Run the entire playbook

```bash
ansible-playbook site.yml
```

#### Run specific playbooks

```bash
# Ubuntu servers only
ansible-playbook ubuntu.yml

# EC2 instances only
ansible-playbook ec2.yml

# Raspberry Pi only
ansible-playbook raspberrypi.yml
```

#### Run against specific hosts

```bash
ansible-playbook site.yml --limit "fox.rewse.jp"
```

#### Run with specific tags

```bash
# Ubuntu basic configuration and package installation only
ansible-playbook ubuntu.yml --tags ubuntu,package

# Docker related only
ansible-playbook site.yml --tags docker
```

#### Check mode (dry run)

```bash
ansible-playbook site.yml --check
```

### 1Password Operations

Sensitive information is managed through 1Password CLI. Use the following pattern in your playbooks and templates:

```yaml
# In playbooks or vars files
db_password: "{{ lookup('pipe', 'op read op://ansible/database/password') }}"
api_key: "{{ lookup('pipe', 'op read op://ansible/api-service/credential') }}"
```

```jinja2
# In templates
password = {{ lookup('pipe', 'op read op://ansible/database/password') }}
```

#### Sign in to 1Password

```bash
# Sign in (required before running playbooks)
op signin

# Verify authentication
op whoami
```

## Inventory

Hosts are classified into the following groups:

- `darwin_business`: Business macOS machines
- `darwin_personal`: Personal macOS machines
- `ubuntu`: Ubuntu servers
- `ec2`: AWS EC2 instances
- `internal`: Internal network hosts
- `raspberrypi`: Raspberry Pi devices
- `singleton_ext1`: External singleton host
- `singleton_int1`: Internal singleton host 1
- `singleton_int2`: Internal singleton host 2

## Variable Management

### Group Variables

Group-specific variables are placed in the `group_vars/<group_name>/` directory:

- `vars`: Regular variables and references to 1Password secrets using `lookup('pipe', 'op read ...')`

### Role Variables

Role-specific variables are defined in each role's `vars/main.yml`.

## Using Tags

For efficient execution, tasks are tagged appropriately:

```bash
# Example: Ubuntu basic configuration only
ansible-playbook ubuntu.yml --tags ubuntu

# Example: Package installation only
ansible-playbook ubuntu.yml --tags package

# Example: Docker related only
ansible-playbook site.yml --tags docker
```

## Best Practices

1. **Verify before changes**: Use the `--check` option before applying to production
2. **Utilize tags**: Use tags to execute only necessary parts
3. **Use 1Password**: Always store sensitive information in 1Password and reference via `lookup('pipe', 'op read ...')`
4. **Gradual application**: Test large changes on specific hosts first
5. **Check logs**: Review logs after execution to ensure no issues

## Troubleshooting

### SSH Connection Errors

```bash
# Disable host key checking (already configured in ansible.cfg)
# Or manually verify SSH connection
ssh ubuntu@<hostname>
```

### 1Password Authentication Errors

```bash
# Verify 1Password CLI is installed
op --version

# Sign in to 1Password
op signin

# Verify authentication status
op whoami
```

### Python Interpreter Errors

```bash
# Python 3 is specified in ansible.cfg
# Verify Python 3 is installed on target hosts
ansible all -m ping
```
