---
inclusion: always
---

# Repository Operations

## 1Password

- Store credentials in the `ansible` vault and commit only Secret References.
- Name an item `System - Consumer` when both identify the credential. Use the complete product name for System and a meaningful account for Consumer; omit a generic or machine-identifier component instead of inventing one. Keep credentials for different systems in separate items.
- Use item IDs rather than titles in committed references. For dynamic selection, map the meaningful selector to an item ID in variables.
- Verify access with a real read through the same environment Ansible uses: `direnv exec . op read op://ansible/<item-id>/<field>`. Do not infer Service Account access from `op whoami` or SSH connectivity; a locked workstation can break lookups independently.
- A failed lookup can leave a host partially converged because earlier tasks remain applied. Restore secret access and rerun the play.

## Playbook Results

Judge a playbook by its process exit code, not only PLAY RECAP. If every host in a play fails, later imported playbooks can be skipped while their hosts still show `failed=0`.

## Zabbix

- Restart `zabbix-server` after creating an item or trigger through the API; `config_cache_reload` can acknowledge the request without making the object evaluate.
- Test agent keys with `zabbix_get` from an address allowed by the agent's `Server=` setting. `zabbix_agentd -t` tests as the invoking user, and localhost is not an allowed source on fox; use `zabbix.rewse.jp` there.
- Emit no value when a UserParameter cannot read its source. Empty output correctly marks the item unsupported; `0` or an epoch-derived age reports false data.
- Omit `searchWildcardsEnabled` for substring searches. Enabling it without `*` changes the match to exact.

## UniFi

- Use Site Manager API keys through `https://api.ui.com/v1/connector/consoles/{consoleId}/proxy/network/...`; a console-local endpoint requires a key created in that console's Integrations settings.
- Use proxied legacy endpoints when the documented API lacks an operation. Legacy updates replace whole objects, so read the object and send it back with the intended changes.
- Match movable objects such as port forwards by stable meaning (name or port), not controller-generated IDs.
- Set `ttlSeconds` explicitly for records that move; `0` uses the 300-second default cache.

## Raspberry Pi NVMe Recovery

- For `Unable to change power state from D3cold to D0`, remove physical power for several seconds. Rebooting or briefly cycling PoE does not reset the controller.
- Identify the failing boundary before changing configuration: failure confined to `/` while USB volumes remain available points to the NVMe path.
- Use shell builtins and `/proc` when binaries under `/usr/bin` are unreadable.
- Suspect the ribbon, HAT, and connectors before the drive when kernel errors are path-related and NVMe SMART reports no media errors.
