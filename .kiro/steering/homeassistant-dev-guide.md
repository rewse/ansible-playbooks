# Home Assistant Development Guide

## Search, Control, Manage, Monitor

When performing the following operations on Home Assistant, you MUST delegate them by `printf "{{prompt}}\n/quit\n" | kiro-cli chat --agent homeassistant`:
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
