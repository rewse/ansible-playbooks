# Repository Rules

## Ansible Conventions

### Roles and Tasks

- Place related roles in nested directories when the hierarchy is meaningful, such as `zabbix/agent/ubuntu`.
- Name tasks `"{submodule} : {Description}"`; keep the submodule lowercase and start the description with a capital letter.
- Store role-specific variables in `roles/<role>/vars/main.yml` and shared inventory values in `group_vars/<group>/vars`.

### Tags

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

### Idempotency

- Notify restart handlers only when managed content changes.
- Keep check mode non-mutating. If a dry-run checkout does not create the source needed by a deployment task, skip that deployment and report why.

## Repository Operations

### 1Password

- Store credentials in the `ansible` vault and commit only Secret References.
- Name an item `System - Consumer` when both identify the credential. Use the complete product name for System and a meaningful account for Consumer; omit a generic or machine-identifier component instead of inventing one. Keep credentials for different systems in separate items.
- Use item IDs rather than titles in committed references. For dynamic selection, map the meaningful selector to an item ID in variables.
- Verify access with a real read through the same environment Ansible uses: `direnv exec . op read op://ansible/<item-id>/<field>`. Do not infer Service Account access from `op whoami` or SSH connectivity; a locked workstation can break lookups independently.
- A failed lookup can leave a host partially converged because earlier tasks remain applied. Restore secret access and rerun the play.

### Playbook Results

Judge a playbook by its process exit code, not only PLAY RECAP. If every host in a play fails, later imported playbooks can be skipped while their hosts still show `failed=0`.

### Zabbix

- Restart `zabbix-server` after creating an item or trigger through the API; `config_cache_reload` can acknowledge the request without making the object evaluate.
- Test agent keys with `zabbix_get` from an address allowed by the agent's `Server=` setting. `zabbix_agentd -t` tests as the invoking user, and localhost is not an allowed source on fox; use `zabbix.rewse.jp` there.
- Emit no value when a UserParameter cannot read its source. Empty output correctly marks the item unsupported; `0` or an epoch-derived age reports false data.
- Omit `searchWildcardsEnabled` for substring searches. Enabling it without `*` changes the match to exact.

### UniFi

- Use Site Manager API keys through `https://api.ui.com/v1/connector/consoles/{consoleId}/proxy/network/...`; a console-local endpoint requires a key created in that console's Integrations settings.
- Use proxied legacy endpoints when the documented API lacks an operation. Legacy updates replace whole objects, so read the object and send it back with the intended changes.
- Match movable objects such as port forwards by stable meaning (name or port), not controller-generated IDs.
- Set `ttlSeconds` explicitly for records that move; `0` uses the 300-second default cache.

### Raspberry Pi NVMe Recovery

- For `Unable to change power state from D3cold to D0`, remove physical power for several seconds. Rebooting or briefly cycling PoE does not reset the controller.
- Identify the failing boundary before changing configuration: failure confined to `/` while USB volumes remain available points to the NVMe path.
- Use shell builtins and `/proc` when binaries under `/usr/bin` are unreadable.
- Suspect the ribbon, HAT, and connectors before the drive when kernel errors are path-related and NVMe SMART reports no media errors.

## Home Assistant

### Live Operations

Read the `mcporter` skill and use `mcporter call home-assistant.<tool>` for live entity discovery, control, configuration, logs, and troubleshooting. Query actual entity IDs and state instead of guessing them.

### YAML

- Follow the Home Assistant YAML Style Guide and use the canonical schema: `triggers`, `conditions`, and `actions`; `trigger` inside trigger entries; `action` for service calls; and `target` for entity, device, or area selection.
- Sort new peer entities alphabetically when their order has no behavior or priority.
- Give every `time_pattern` trigger a chosen `seconds` value from 0 through 59 so periodic automations do not start together.

### `tuya_local` Recovery

1. Treat error 914 (`Check device key or version`) as a generic handshake failure, not proof that credentials changed.
2. Power-cycle the device, wait for it to rejoin, then reload its config entry. Reloading is required because `tuya_local` can stop retrying after setup fails; `restored: true` indicates only a registry placeholder remains.
3. If reload reports `has already been setup`, restart Home Assistant instead of repeating reloads.
4. If the device stays unavailable, distinguish a powered but hung device from one without power. Check its plug power sensor, a UniFi `Connected` event, and TCP port 6668. UniFi `last_seen` is not a connection timestamp.
5. Suspect Device ID or Local Key only after the device is confirmed online and reload still fails. Retrieve fresh Tuya credentials, compare both values, and recreate the config entry if the Device ID changed.
6. Stop when the entity recovers. Do not follow recovery with unrelated options changes because another reload can return the entry to the `has already been setup` state.

`tuya_local` discovery overwrites `host` with the discovered IP, so configuring a hostname does not persist. Use `tuya_local` rather than LocalTuya for devices that LocalTuya does not support, such as the Fancy Sync Box.
