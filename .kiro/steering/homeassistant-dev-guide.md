# Home Assistant Development Guide

## Search, Control, Manage, Monitor

When performing the following operations on Home Assistant, you MUST read `mcporter` skill and use `mcporter call home-assistant.<tool>`:
- Searching and finding Home Assistant entities, devices, and configurations
- Controlling smart home devices and automations
- Managing Home Assistant setup, configuration, and troubleshooting
- Monitoring system status, logs, and performance
- Providing guidance on best practices for home automation
- Helping with YAML configurations, scripts, and automations
- Assisting with integrations and add-ons

## YAML

- When adding new entities, you SHOULD consider alphabetical sorting within the file

### YAML Style Guide

You MUST follow [Home Assistant YAML Style Guide](https://developers.home-assistant.io/docs/documenting/yaml-style-guide/).

### New YAML Syntax

- You MUST use the new syntax
- Since Home Assistant 2024.8, the following YAML syntax changes were introduced

- `service:` → `action:`
  - e.g. `service: light.turn_on` → `action: light.turn_on`
- `trigger:` → `triggers:` (top-level pluralization)
- `condition:` → `conditions:` (top-level pluralization)
- `action:` → `actions:` (top-level pluralization)
- `platform:` → `trigger:`
  - inside `triggers:` block, e.g. `platform: state` → `trigger: state`
- `data: entity_id:` → `target: entity_id:`
  - use `target:` for `entity_id`, `device_id`, `area_id`; other options stay in `data:`

```yaml
# New syntax example
automation:
  triggers:
    - trigger: state
      entity_id: binary_sensor.motion
  conditions:
    - condition: state
      entity_id: sun.sun
      state: below_horizon
  actions:
    - action: light.turn_on
      target:
        entity_id: light.living_room
      data:
        brightness: 255
```

Reference:
- [Home Assistant 2024.8 Release Notes](https://www.home-assistant.io/blog/2024/08/07/release-20248/)
- [Home Assistant 2024.10 Release Notes](https://www.home-assistant.io/blog/2024/10/02/release-202410/)

## Automation

When using `trigger: time_pattern`, you MUST add `seconds` with a random number (0 to 59) to prevent multiple automations from running at the same time.

## Troubleshooting

### tuya_local: Entity Unavailable

When a `tuya_local` entity becomes `unavailable`:

1. Check HA system logs for `tuya_local` errors:
   - `"Check device key or version"` → Local key or Device ID has changed
   - `"device offline"` → Network unreachable or key mismatch (tuya_local reports offline when handshake fails)

2. Verify network connectivity from HA server (`ssh fox`):
   - DNS resolution: `dig +short <hostname>`
   - Ping: `ping <ip>`
   - Port: `nc -z -w 3 <ip> 6668`

3. If network is fine, the Device ID and/or Local Key likely rotated. Retrieve new credentials:
   ```bash
   .venv/bin/python3 -m tinytuya wizard
   ```
   - API Key/Secret: from Tuya IoT Platform project
   - Region: `us`
   - Compare the returned `id` and `key` with current HA config

4. If Device ID changed, delete the old tuya_local entry in HA and re-add with new ID + key

**Known causes of ID/key rotation:**
- Removing and re-adding device in Tuya/Smart Life app
- Firmware updates (rare)
- Tuya cloud-side maintenance (rare, unannounced)

**Note:** LocalTuya can auto-sync keys but does not support all devices (e.g., Fancy Sync Box). For unsupported devices, tuya_local is required and manual key updates are unavoidable.
