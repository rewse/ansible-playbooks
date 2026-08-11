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

Assume the device has hung. That is the common case, and it clears with a power cycle followed by a config entry reload. Credential rotation is rare and is the last hypothesis, not the first.

Do not read `"Check device key or version"` (error 914) as evidence that the key changed. It appears whenever the handshake fails, including when the device has hung while holding a perfectly valid key.

1. Power cycle the device, then reload its config entry:
   ```bash
   mcporter call home-assistant.ha_call_service domain=switch service=turn_off entity_id=<plug>
   # wait 30 seconds
   mcporter call home-assistant.ha_call_service domain=switch service=turn_on entity_id=<plug>
   # wait a minute for the device to rejoin
   mcporter call home-assistant.ha_call_service domain=homeassistant service=reload_config_entry entity_id=<entity>
   ```
   The reload is the step that matters. Once setup has failed with `"tuya-local device offline"`, the integration stops retrying, so the entity stays `unavailable` long after the device is back on the network. A device that reports `restored: true` is a registry placeholder with no integration behind it, which is what this state looks like from `ha_get_state`.

2. If a reload logs `ValueError: Config entry ... has already been setup!`, restart Home Assistant. No number of reloads clears that state, and repeating them may prolong it.

3. If the device never comes back, separate "powered but hung" from "not powered": read the plug's power sensor, and check the UniFi connectivity log for a `Connected` event. `ssh fox 'nc -z -w 3 <ip> 6668'` tells you whether it is ready to talk. A device drawing power with no `Connected` event has hung beyond what a plug cycle fixes, and needs to be unplugged physically.

4. Only once the device is confirmed on the network and reloads still fail, suspect the Device ID or Local Key. Retrieve new credentials:
   ```bash
   .venv/bin/python3 -m tinytuya wizard
   ```
   - API Key/Secret: from Tuya IoT Platform project (`/home/tats/.config/configstore/@tuyapi/cli.json`)
   - Region: `us`
   - Compare the returned `id` and `key` with current HA config
   - Non-interactive alternative:
     ```bash
     uvx --from tinytuya python3 -c "
     import tinytuya, json
     c = tinytuya.Cloud(apiRegion='us', apiKey='...', apiSecret='...')
     devices = c.getdevices()
     for d in devices:
         if d.get('id') == '<device_id>':
             print(json.dumps(d, indent=2))
     "
     ```

5. If Device ID changed, delete the old tuya_local entry in HA and re-add with new ID + key

Stop as soon as the entity is back. Do not follow a recovery with unrelated tidying of the same entry: an options flow update reloads the entry and can leave it in the `has already been setup` state, turning a fixed problem into one that needs a restart.

Reading the evidence:
- UniFi's `last_seen` is the last observation of a client, not the time it connected. Take rejoin timing from `Connected` events in the connectivity log. The Fancy Sync Box associates about 20 seconds after power returns.
- High ICMP latency from a device is not a signal problem. Compare against the UniFi site latency and the client's dBm before blaming the link.
- tuya_local discovery overwrites `host` with the IP it discovers, so configuring a hostname does not stick.

**Known causes of ID/key rotation:**
- Removing and re-adding device in Tuya/Smart Life app
- Firmware updates (rare)
- Tuya cloud-side maintenance (rare, unannounced)

**Note:** LocalTuya can auto-sync keys but does not support all devices (e.g., Fancy Sync Box). For unsupported devices, tuya_local is required and manual key updates are unavoidable.
