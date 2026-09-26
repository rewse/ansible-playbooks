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
- 1Password CLI (`op`) installed (version 2.18.0 or later)
- direnv installed (optional but recommended)

### Install Ansible Collections

This repository depends on external Ansible collections. Install them before running any playbook:

```bash
ansible-galaxy collection install -r requirements.yml
```

### 1Password Setup

This repository uses 1Password Service Accounts for authentication. Service Accounts allow automated access to secrets without interactive sign-in.

#### Using direnv (Recommended)

1. Install direnv:
   ```bash
   # Ubuntu
   sudo apt install direnv

   # macOS
   brew install direnv
   ```

2. Add direnv hook to your shell (`~/.bashrc` or `~/.zshrc`):
   ```bash
   eval "$(direnv hook bash)"  # or zsh
   ```

3. Reload your shell and allow direnv:
   ```bash
   source ~/.bashrc  # or ~/.zshrc
   cd /path/to/ansible-playbooks
   direnv allow
   ```

The `.envrc` file contains the Service Account token and will be automatically loaded.

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

Tags follow the rules in `AGENTS.md`: a role-name tag, a `<role>_<component>` tag per component, and `update` for version updates.

```bash
# One role
ansible-playbook ubuntu.yml --tags ubuntu

# One component of a role
ansible-playbook singleton_int1.yml --tags filebrowser_container

# Package upgrades and new third-party releases only
ansible-playbook site.yml --tags update
```

#### Check mode (dry run)

```bash
ansible-playbook site.yml --check
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

`AGENTS.md` defines where each kind of variable belongs. In short:

- `group_vars/all/`: A short list of site-wide shared values
- `group_vars/<group>/`: Desired state per group
- `roles/<role>/defaults/main.yml`: Role inputs the inventory may override
- `roles/<role>/vars/main.yml`: Role constants

Secrets live in the 1Password `ansible` vault. Commit only Secret References that point to item IDs, never secret values.

## Best Practices

1. **Verify before changes**: Use `--check --diff` before applying to a live host
2. **Utilize tags**: Use tags to execute only necessary parts
3. **Use 1Password**: Store sensitive information in 1Password and commit only Secret References
4. **Gradual application**: Test large changes on specific hosts first
5. **Check results**: Judge a run by its exit code, and confirm a second run reports `changed=0`
6. **Lint**: Run `uvx pre-commit run --all-files` before committing
