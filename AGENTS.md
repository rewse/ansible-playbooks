# Repository Rules

## Ansible Conventions

`roles/filebrowser` is the reference implementation of these rules. Roles not yet migrated still have entries in `.ansible-lint-ignore`; migrate a role by making it lint-clean and deleting its lines there.

### Update Policy

- Upgrade OS package managers (apt, brew) and their official repositories to the latest version on every run, in the OS role's final `upgrade.yml`.
- Resolve third-party container images, GitHub releases, git repositories, and Home Assistant custom components at run time with the `aged_release` lookup, which returns the newest release published at least `supply_chain_cooldown_days` days ago. Pin the result by content: an image as `tag@digest`, a release asset by its sha256 when the release publishes one, and a checkout by commit SHA.
- Track release tags rather than branches; for a repository without tags, use `github-commit:` for the newest commit that old.
- Track the default branch of repositories and images owned by this account without a cooldown (`days=0`).
- Pass `supply_chain_cooldown_environment` as `environment` to every task that runs npm or uv, so npm and PyPI releases get the same cooldown. A `uv sync` against a committed lockfile of this account's own repository is exempt. Keep `min-release-age` in the chezmoi npmrc and `exclude-newer` in the chezmoi uv.toml at the same number of days for interactive use.
- Install the latest release of software outside GitHub and of vendor installers without a cooldown, as with OS packages: use the vendor's unversioned download or apt repository, and update installed tools with their own update command under the `update` tag.
- Install software by the method its vendor documents (official apt repository, Homebrew, installer script). Use another method only when the official one is unavailable on that OS or platform, and state why in a comment.
- Pin a version only as an exception: define `<role>_<component>_version` and state the reason in a comment. Do not otherwise keep versions in variables.

### Role Design

- Write one playbook per host type, one role per function, and one `tasks/<component>.yml` per component.
- Name a host type after its role, not its host: the playbook with hyphens (`home-primary.yml`) and its inventory group with underscores (`home_primary`).
- Keep in an OS role (`ubuntu`, `darwin`) or platform role (`raspberrypi`, `ec2`) only configuration that is meaningful on that OS or platform alone, such as timezone, ssh, sysctl, journald, swap, and the package list.
- Promote a component to its own role when it is used by more than one OS or host type, when it is an application or service with its own configuration, handlers, or version lifecycle, or when it no longer fits in one task file.
- Express differences between host types as inventory data (for example `darwin_extra_packages`) or as separate roles in the type's playbook, not as per-type roles.
- When a role publishes a service that requires a login, give it a `fail2ban` component with a filter and a jail for that service, as `roles/filebrowser` does.

### File Locations

- Deploy each containerized service as its own Compose project in `/etc/compose/<role>/compose.yaml`, rendered from `templates/compose.yaml.j2` with `name: <role>`. The file name follows Docker's preference and is the one exception to the `.yml` extension.
- Keep service data in `/srv/<role>`.
- `homeassistant_ha_secondary` uses the `homeassistant` project at the primary's path so the failover scripts address both hosts alike.
- Check out source that is copied into place under `/usr/local/src/<name>`, and software that runs from its checkout under `/opt/<name>`.

### Platform Differences

- When only values differ (package names, paths, service names), load `vars/<distribution>.yml` from `tasks/set_vars.yml`.
- When steps differ slightly, include `tasks/<variant>.yml` selected by a fact or an inventory variable such as `zabbix_agent_platform`. Never select by inventory group name.
- When one product needs unrelated steps per OS but shares its purpose and values, import `tasks/linux.yml` and `tasks/darwin.yml` conditioned on `ansible_facts['system']`, as `roles/restic` does.
- When the implementations are unrelated, write separate roles.
- Name an OS by its lowercase Ansible fact: `distribution` for Linux (`ubuntu`) and `system` for macOS (`darwin`, never `macos`). Name hardware and clouds (`raspberrypi`, `ec2`) as platforms, distinct from OS names.

### Role Names

- Use flat snake_case matching `^[a-z][a-z0-9_]*$`, with no nested role directories and no hyphens. Express hierarchy with a prefix, such as `zabbix_server` or `postfix_client`. Nested roles are resolved by their last directory name, which breaks variable prefixes.
- Name a role that installs and configures one product after the product (`mosquitto`, `restic`). Name a role that combines several products for one purpose after the function (`nas`, `nvr`, `sslcert`).
- Playbook file names use hyphens (`darwin-personal.yml`).

### Task Names

- Write every task, handler, and play name in the imperative with a leading capital, without the role name; Ansible prefixes the role name in its output.
- Keep `tasks/main.yml` to `ansible.builtin.import_tasks` lines, one per component file.
- Prefix task names in a component file with the component name: `container | Resolve aged image`. Name components after what they manage and never repeat the role name.
- Put Jinja only at the end of a name.

### Tags

Use only these tags, written as an indented YAML list:

| Tag | Where | Purpose |
|---|---|---|
| Role name | On the role in the playbook and on the same role in `meta/main.yml` dependencies | Run or skip one role and its dependencies |
| `<role>_<component>` | On the `import_tasks` in `tasks/main.yml` | Run one component |
| `update` | On the `import_tasks` of components that resolve or apply new versions, and on `upgrade.yml` | Run updates only |
| `always` | On `set_vars.yml` and fact setup only | Load values every other tag needs |

- Make every component file self-contained, including its prerequisite directories, checkouts, and configuration, so each tag runs alone.
- Tag the whole component with `update`, not just the version lookup, so the resolved version is also applied.
- Repeat the role, component, and any `update` tag in `apply.tags` of a dynamic `include_role` or `include_tasks`; tags on a dynamic include select only the include itself, not the tasks it loads.
- Do not add operation tags such as `install` or `config`.

```yaml
- name: Import container tasks
  ansible.builtin.import_tasks: container.yml
  tags:
    - filebrowser_container
    - update
```

### Ordering

- In a playbook, order roles by tier (OS, platform, cross-OS tools, services) and alphabetically within a tier. Declare real ordering dependencies in `meta/main.yml`.
- In `tasks/main.yml`, import `set_vars.yml` and fact setup first, then components in dependency order and otherwise alphabetically; an OS role ends with `upgrade.yml`.
- In a component file, order tasks as prerequisites, version resolution, installation, configuration, service enablement, and removal of legacy state.
- Restart services through handlers. Add `meta: flush_handlers` only when a later component needs the restarted service.
- Give a handler the same name and body in every role that defines it, such as `Reload Apache`. Ansible runs only the last one loaded, so when the order of two handlers matters, notify them as `<role> : <handler>`.
- Delete a legacy-removal task (`state: absent`) once every host has converged.

### Variables

| Location | Contents |
|---|---|
| Inline in the task | A value used by one task and clear in place, such as `mode` |
| `vars/main.yml` | Constants identical on every host: values used more than once, lists, URLs, ports, UIDs, and Secret References |
| `vars/<distribution>.yml` | Constants that differ by OS |
| `defaults/main.yml` | Inputs the inventory may override; list inputs without a meaningful default commented out |
| `inventory/group_vars/<group>/<role>.yml`, `inventory/host_vars/<host>/<role>.yml` | Desired state per group or host, one file per role |
| `inventory/host_vars/<host>/ansible.yml` | Connection variables such as `ansible_port` only |
| `inventory/group_vars/all/site.yml` | Site-wide shared values |

- Prefix every variable a role defines with the role name. Prefix `register` and `set_fact` results with `__<role>_`.
- Only these shared values in `inventory/group_vars/all/site.yml` go without a prefix: `admin`, `email`, `global_ip`, `ipv6`, `supply_chain_cooldown_days`, and `supply_chain_cooldown_environment`. Give a new shared value a specific name (`local_network`, not `local`) and add it here.
- Put a Secret Reference in the role's `vars/main.yml` when it is the same on every host and in the inventory when it differs.
- Do not use play vars, `include_vars` outside `set_vars.yml`, or extra vars for desired state.

### Quoting

- Quote YAML strings with double quotes, and strings inside Jinja expressions with single quotes: `"{{ x | default('a') }}"`.
- Leave keywords, numbers, booleans, and paths unquoted unless YAML syntax requires quotes, such as a value starting with `{` or containing `: `.
- Write `mode` as a double-quoted four-digit octal string, such as `"0644"`.
- Use single quotes for strings with backslashes, such as regular expressions, so they need no escaping.
- Quote a task name only when it contains `: `.

### Quality

- Keep check mode non-mutating and free of failures. If a dry-run checkout does not create the source a later task needs, skip that task and report why.
- Make a second run report `changed=0`. Notify restart handlers only when managed content changes.
- Judge a run by its process exit code, not only PLAY RECAP. If every host in a play fails, later imported playbooks can be skipped while their hosts still show `failed=0`.
- Use `command` or `shell` only when no module exists, state why in a comment, and always set `changed_when`.
- Pass package lists to the package module at once instead of looping over `item`.
- Use `set_fact` only when a value must be computed at run time.
- Use `template` for files the role owns entirely; reserve `lineinfile` for one-line edits to system files.
- Start every template with `{{ ansible_managed | comment }}`, after `---` in a YAML template. A template rendered into a `blockinfile` block is exempt because the block marker identifies it. Do not use `backup: true`.
- Give every `debug` a `verbosity`.

### Lint

- Lint through pre-commit (`uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`) locally and in CI. It runs actionlint for GitHub Actions workflows, ansible-lint for Ansible content, basedpyright and ruff for Python, check-jsonschema for the Dependabot config, shellcheck for shell scripts, and zizmor for GitHub Actions workflows. `.yamllint` configures ansible-lint's `yaml` rule; do not run yamllint separately.
- `roles/homeassistant/files/` is excluded from lint.
- Do not add entries to `.ansible-lint-ignore` for new code.

## Repository Operations

### Running Playbooks

- Limit every check and apply to the changed roles or components with `--tags`, because a full playbook run takes a long time. Run a full playbook only when a change can affect roles you did not edit, such as a renamed handler or a shared variable, and for the final verification of a change set.

### 1Password

- Store credentials in the `ansible` vault and commit only Secret References.
- Name an item `System - Consumer` when both identify the credential. Use the complete product name for System and a meaningful account for Consumer; omit a generic or machine-identifier component instead of inventing one. Keep credentials for different systems in separate items.
- Use item IDs rather than titles in committed references. For dynamic selection, map the meaningful selector to an item ID in variables.
- Verify access with a real read through the same environment Ansible uses: `direnv exec . op read op://ansible/<item-id>/<field>`. Do not infer Service Account access from `op whoami` or SSH connectivity; a locked workstation can break lookups independently.
- A failed lookup can leave a host partially converged because earlier tasks remain applied. Restore secret access and rerun the play.

### Home Assistant

- Read the `mcporter` skill and use `mcporter call home-assistant.<tool>` for live entity discovery, control, configuration, logs, and troubleshooting. Query actual entity IDs and state instead of guessing them.
- Follow the Home Assistant YAML Style Guide and use the canonical schema: `triggers`, `conditions`, and `actions`; `trigger` inside trigger entries; `action` for service calls; and `target` for entity, device, or area selection.
- Sort new peer entities alphabetically when their order has no behavior or priority.
- To add a configuration domain, add its `!include` line to `roles/homeassistant/templates/configuration.yaml.j2`, add the file to `homeassistant_config_files` (or `homeassistant_reloadable_config_files` when Home Assistant reloads it without a restart) in `roles/homeassistant/vars/main.yml`, and put the file in `roles/homeassistant/files/`. Automation files named `automations-*.yaml` are deployed without being listed.
- Give every `time_pattern` trigger a chosen `seconds` value from 0 through 59 so periodic automations do not start together.

### UniFi

- Use Site Manager API keys through `https://api.ui.com/v1/connector/consoles/{consoleId}/proxy/network/...`; a console-local endpoint requires a key created in that console's Integrations settings.
- Use proxied legacy endpoints when the documented API lacks an operation. Legacy updates replace whole objects, so read the object and send it back with the intended changes.
- Match movable objects such as port forwards by stable meaning (name or port), not controller-generated IDs.
- Set `ttlSeconds` explicitly for records that move; `0` uses the 300-second default cache.

### Zabbix

- Restart `zabbix-server` after creating an item or trigger through the API; `config_cache_reload` can acknowledge the request without making the object evaluate.
- Test agent keys with `zabbix_get` from an address allowed by the agent's `Server=` setting. `zabbix_agentd -t` tests as the invoking user, and localhost is not an allowed source on fox; use `zabbix.rewse.jp` there.
- Emit no value when a UserParameter cannot read its source. Empty output correctly marks the item unsupported; `0` or an epoch-derived age reports false data.
- Omit `searchWildcardsEnabled` for substring searches. Enabling it without `*` changes the match to exact.

## Troubleshooting

### Raspberry Pi NVMe Recovery

- For `Unable to change power state from D3cold to D0`, remove physical power for several seconds. Rebooting or briefly cycling PoE does not reset the controller.
- Identify the failing boundary before changing configuration: failure confined to `/` while USB volumes remain available points to the NVMe path.
- Use shell builtins and `/proc` when binaries under `/usr/bin` are unreadable.
- Suspect the ribbon, HAT, and connectors before the drive when kernel errors are path-related and NVMe SMART reports no media errors.

### `tuya_local` Recovery

1. Treat error 914 (`Check device key or version`) as a generic handshake failure, not proof that credentials changed.
2. Power-cycle the device, wait for it to rejoin, then reload its config entry. Reloading is required because `tuya_local` can stop retrying after setup fails; `restored: true` indicates only a registry placeholder remains.
3. If reload reports `has already been setup`, restart Home Assistant instead of repeating reloads.
4. If the device stays unavailable, distinguish a powered but hung device from one without power. Check its plug power sensor, a UniFi `Connected` event, and TCP port 6668. UniFi `last_seen` is not a connection timestamp.
5. Suspect Device ID or Local Key only after the device is confirmed online and reload still fails. Retrieve fresh Tuya credentials, compare both values, and recreate the config entry if the Device ID changed.
6. Stop when the entity recovers. Do not follow recovery with unrelated options changes because another reload can return the entry to the `has already been setup` state.

`tuya_local` discovery overwrites `host` with the discovered IP, so configuring a hostname does not persist. Use `tuya_local` rather than LocalTuya for devices that LocalTuya does not support, such as the Fancy Sync Box.
