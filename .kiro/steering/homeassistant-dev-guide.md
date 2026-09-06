---
inclusion: always
---

# Home Assistant

## Live Operations

Read the `mcporter` skill and use `mcporter call home-assistant.<tool>` for live entity discovery, control, configuration, logs, and troubleshooting. Query actual entity IDs and state instead of guessing them.

## YAML

- Follow the Home Assistant YAML Style Guide and use the canonical schema: `triggers`, `conditions`, and `actions`; `trigger` inside trigger entries; `action` for service calls; and `target` for entity, device, or area selection.
- Sort new peer entities alphabetically when their order has no behavior or priority.
- Give every `time_pattern` trigger a chosen `seconds` value from 0 through 59 so periodic automations do not start together.

## `tuya_local` Recovery

1. Treat error 914 (`Check device key or version`) as a generic handshake failure, not proof that credentials changed.
2. Power-cycle the device, wait for it to rejoin, then reload its config entry. Reloading is required because `tuya_local` can stop retrying after setup fails; `restored: true` indicates only a registry placeholder remains.
3. If reload reports `has already been setup`, restart Home Assistant instead of repeating reloads.
4. If the device stays unavailable, distinguish a powered but hung device from one without power. Check its plug power sensor, a UniFi `Connected` event, and TCP port 6668. UniFi `last_seen` is not a connection timestamp.
5. Suspect Device ID or Local Key only after the device is confirmed online and reload still fails. Retrieve fresh Tuya credentials, compare both values, and recreate the config entry if the Device ID changed.
6. Stop when the entity recovers. Do not follow recovery with unrelated options changes because another reload can return the entry to the `has already been setup` state.

`tuya_local` discovery overwrites `host` with the discovered IP, so configuring a hostname does not persist. Use `tuya_local` rather than LocalTuya for devices that LocalTuya does not support, such as the Fancy Sync Box.
