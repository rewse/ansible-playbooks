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
# Verify authentication the way Ansible reaches it
direnv exec . op read op://ansible/database/password

# Read secrets
op read op://ansible/database/password

# Usage example in Ansible
# In playbooks or vars files:
# db_password: "{{ lookup('pipe', 'op read op://ansible/database/password') }}"
```

**Note**: Service Accounts work in interactive shells but may fail in automated contexts due to a known 1Password CLI limitation.

Verify with a real `op read` through `direnv exec .`, not with `op whoami`. The desktop session and the Service Account are independent: `op whoami` can report `account is not signed in` while the Service Account still reads, and the reverse also happens when the workstation locks. A locked workstation breaks the lookups while SSH keeps working, so a successful `ssh` says nothing about whether a play will get its secrets.

A failed lookup aborts only the task that needed it, naming the file in an `Origin:` line. Everything before it has already been applied, so a play can leave a host half converged; re-run it once the secret is readable.

## Ansible Syntax

Follow [Ansible YAML Syntax](https://docs.ansible.com/projects/ansible/latest/reference_appendices/YAMLSyntax.html).

## Best Practices

- Use tags for selective execution
- Store sensitive data in 1Password and reference with `lookup('pipe', 'op read ...')`
- Use group_vars when saving share configuration
- Verify with `--check` before applying changes
- Keep role-specific variables in `role/vars` directories
- Don't add temporary or one-time fixes to playbooks; apply them directly via SSH instead
- Judge a playbook run by its exit code, not by the per-host `failed` counts in PLAY RECAP. When every host in a play fails, the run ends and the remaining imported playbooks are skipped without a banner, so every host can still report `failed=0` while later plays were never applied. Most plays in `site.yml` target a single host, where one failure is enough to trigger this.

## Troubleshooting

### Zabbix

Restart `zabbix-server` after creating an item or a trigger through the API. `zabbix_server -R config_cache_reload` answers `Runtime control command was forwarded successfully`, writes nothing to the log, and leaves the new object unevaluated: a trigger stayed silent for 45 minutes and a pair of items produced no value for longer than their 10 minute interval, both starting to work within minutes of a restart.

Test an agent key with `zabbix_get`, not with `zabbix_agentd -t`. The latter runs as whoever invoked it, so `sudo zabbix_agentd -t` answers as root and says nothing about a key the agent will run as `zabbix`.

Reach an agent by the address in its `Server=`, since it refuses every other source. On fox that is `zabbix.rewse.jp`, which resolves to the host's global IPv6, so `zabbix_get -s 127.0.0.1` fails for every key with `Received empty response ... because of access permissions`. That message is about the source address, not the key.

Print nothing from a UserParameter that cannot read its value. Empty output makes the item unsupported, which is the state that means "cannot tell"; returning 0 or an age counted from the epoch reports a value that was never read as though it were real, and alerts on it.

Pass `search` without `searchWildcardsEnabled` when a substring match is wanted. With the flag on, a pattern holding no `*` becomes an exact match: `search: {key_: "icmpping"}` returned 1 item of 23 and hid every `icmppingloss` and `icmppingsec`.

### A Raspberry Pi Whose NVMe Has Stopped Answering

Remove the power and wait minutes. Neither a reboot nor a PoE blink clears it, and UniFi can only blink PoE, so this needs someone at the machine.

| Action | Result |
| --- | --- |
| Reboot | `/` remounted read-only 91 seconds in |
| PoE off and on | every executable under `/usr/bin` unreadable 18 seconds in |
| Power removed for minutes | normal boot, no NVMe errors, `/` read-write |

`Unable to change power state from D3cold to D0` is the controller stuck in a low power state, which a brief interruption does not leave.

Check whether the boundary of the failure matches a disk boundary. Everything on `/` died while Samba kept serving the volumes in the USB enclosure, which is what identified a failing disk rather than a configuration change.

Read the state with bash builtins. `while read` and `/proc` still work when `cat` and `grep` can no longer be loaded.

Do not trust the first error. `Read-error on swap-device` appeared first and swap turned out to be irrelevant: removing it changed nothing, and `/usr/bin/sudo: Input/output error` on the next boot pointed at `/` instead.

Suspect the path before the drive. `nvme smart-log` reported `media_errors: 0` and `num_err_log_entries: 0` against 124 kernel I/O errors, and the kernel's `sct 0x3` is Path Related Status rather than a media error, so the ribbon, the HAT and the connectors come before any thought of replacing the drive.
