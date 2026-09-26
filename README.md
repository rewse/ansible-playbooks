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
├── ansible.cfg              # Ansible configuration file
├── inventory/
│   ├── hosts                # Hosts and groups only
│   ├── group_vars/all/      # Site-wide shared values
│   └── host_vars/<host>/    # Per-host values, one file per role
├── site.yml                 # All Ubuntu host types
├── home-primary.yml         # Home primary (fox)
├── home-secondary.yml       # Home secondary (hotel)
├── cloud-workstation.yml    # Cloud workstation on EC2 (alfa)
├── darwin-business.yml      # macOS business
├── darwin-personal.yml      # macOS personal
├── udm.yml                  # UniFi Dream Machine
└── roles/                   # One role per function
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

#### Run one host type

Each host type has one playbook that fully configures its hosts.

```bash
ansible-playbook home-primary.yml
ansible-playbook home-secondary.yml
ansible-playbook cloud-workstation.yml
```

#### Run against specific hosts

```bash
ansible-playbook site.yml --limit "fox.rewse.jp"
```

#### Run with specific tags

Tags follow the rules in `AGENTS.md`: a role-name tag, a `<role>_<component>` tag per component, and `update` for version updates.

```bash
# One role
ansible-playbook home-primary.yml --tags ubuntu

# One component of a role
ansible-playbook home-primary.yml --tags filebrowser_container

# Package upgrades and new third-party releases only
ansible-playbook site.yml --tags update
```

#### Check mode (dry run)

```bash
ansible-playbook site.yml --check
```

## Inventory

`inventory/hosts` defines one group per host type and a few groups for ad hoc commands:

- `cloud_workstation`, `home_primary`, `home_secondary`: Ubuntu host types
- `darwin_business`, `darwin_personal`: macOS host types
- `udm`: UniFi Dream Machine
- `ec2`, `raspberrypi`, `ubuntu`: Hosts by platform or OS, for ad hoc commands such as `ansible raspberrypi -m ping`

## Variable Management

`AGENTS.md` defines where each kind of variable belongs. In short:

- `inventory/group_vars/all/site.yml`: A short list of site-wide shared values
- `inventory/host_vars/<host>/<role>.yml`: Desired state per host
- `inventory/host_vars/<host>/ansible.yml`: Connection variables such as `ansible_port`
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
