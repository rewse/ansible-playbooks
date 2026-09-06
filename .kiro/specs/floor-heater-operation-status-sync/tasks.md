# 床暖房operation status双方向同期 Implementation Plan

> **For agentic workers:** 承認済みの設計に従い、各チェック項目を順番に実行する。

**Goal:** リビングと書斎の床暖房operation statusを、オン・オフとも10秒の猶予後に双方向同期する。

**Architecture:** 既存のリビング空調自動化ファイルへ、4件のstateトリガーを持つ自動化を追加する。トリガー成立後は同期先が逆状態の場合だけ操作し、`mode: queued`で競合する操作を直列化する。

**Tech Stack:** Ansible、Home Assistant 2026.8、YAML、Home Assistant MCP

## Global Constraints

- `switch.living_room_floor_heater_operation_status`と`switch.study_floor_heater_operation_status`だけを同期対象にする。
- オンとオフのどちらも、起点側が変更後の状態を10秒間維持した場合だけ同期する。
- 同期先が`unknown`または`unavailable`の場合は操作しない。
- 実機スイッチを使った自動テストは行わない。
- コミットは明示された場合だけ作成する。

---

### Task 1: 自動化の契約テストと実装

**Files:**
- Create: `roles/homeassistant/tests/floor_heater_operation_status_sync.yml`
- Modify: `roles/homeassistant/files/automations-living-room-climates.yaml:1206`

**Interfaces:**
- Consumes: 2件のECHONET Lite switch entityとHome Assistantのstate trigger、trigger condition、switch action
- Produces: `automation.sync_living_area_floor_heater_operation_status`

- [x] **Step 1: 失敗する契約テストを作成する**

テストは対象自動化をIDで抽出し、4件のトリガー、10秒の`for`、4方向の状態条件と操作、`queued`モードを検査する。

- [x] **Step 2: テストが対象自動化の不足で失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/floor_heater_operation_status_sync.yml`
Expected: `homeassistant_floor_heater_sync_automations | length == 1`がfalseになりFAILする。

- [x] **Step 3: 自動化を追加する**

`automation.sync_living_area_floor_heater_operation_status`に次を定義する。

```yaml
triggers:
  - id: living_room_off
    trigger: state
    entity_id: switch.living_room_floor_heater_operation_status
    to: "off"
    for:
      seconds: 10
  - id: living_room_on
    trigger: state
    entity_id: switch.living_room_floor_heater_operation_status
    to: "on"
    for:
      seconds: 10
  - id: study_off
    trigger: state
    entity_id: switch.study_floor_heater_operation_status
    to: "off"
    for:
      seconds: 10
  - id: study_on
    trigger: state
    entity_id: switch.study_floor_heater_operation_status
    to: "on"
    for:
      seconds: 10
mode: queued
max: 4
```

`choose`の各分岐では`condition: trigger`と同期先の`condition: state`を組み合わせ、対応する`switch.turn_on`または`switch.turn_off`を1回だけ呼ぶ。

- [x] **Step 4: 契約テストを通す**

Run: `ansible-playbook roles/homeassistant/tests/floor_heater_operation_status_sync.yml`
Expected: `failed=0`で終了する。

### Task 2: 配備と実環境検証

**Files:**
- Deploy: `roles/homeassistant/files/automations-living-room-climates.yaml` to `/srv/homeassistant/config/automations/automations-living-room-climates.yaml`

**Interfaces:**
- Consumes: `singleton_int1.yml`、`homeassistant_automation_config`タグ、Home Assistant automation reload
- Produces: 有効な`automation.sync_living_area_floor_heater_operation_status`

- [x] **Step 1: Ansible構文を検証する**

Run: `ansible-playbook singleton_int1.yml --syntax-check`
Expected: exit code 0。secret lookupで実行不能な場合は、契約テストの`--syntax-check`と通常実行を代替証拠にする。

- [x] **Step 2: 限定check modeで差分を確認する**

Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant_automation_config --check --diff`
Expected: 対象自動化ファイルの更新だけが報告される。

- [x] **Step 3: 対象ファイルを配備する**

Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant_automation_config`
Expected: process exit code 0で、対象copy taskがchangedになる。

- [x] **Step 4: Home Assistantの自動化を再読み込みする**

Home Assistant MCPの`ha_reload_core`でautomationsを再読み込みする。

- [x] **Step 5: 実環境の設定を確認する**

対象automation entityが有効であること、4件のトリガーと`queued`モードが読み込まれたこと、対象スイッチを操作していないことをMCPで確認する。
