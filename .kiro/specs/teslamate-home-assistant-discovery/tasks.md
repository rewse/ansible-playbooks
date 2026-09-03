# TeslaMate Home Assistant discovery Implementation Plan

> **Current refresh contract:** `sensor.model_y_state`がactiveな間だけ10分ごとに`climate.model_y_climate`を更新する。Task 2以下の30分契約は初回配備時の実行記録であり、現在の動作は`design.md`、automation、契約テストを正とする。
> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or execute the tasks inline in order. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** TeslaMate MQTT discoveryを有効化し、Tesla Fleet標準pollingを停止したうえでactive状態の間だけ10分間隔で手動更新する。

**Architecture:** TeslaMateはMQTT discovery payloadを既存Mosquittoへpublishし、Home Assistantが読み取り用entityを自動登録する。Tesla Fleet config entryの標準pollingはHome Assistantのstorage設定で停止する。YAML automationは`sensor.model_y_state`がactiveへ遷移したときとactive中の10分ごとに共有coordinatorを1回だけ手動更新する。

**Tech Stack:** Ansible、YAML、Jinja2、Home Assistant 2026.8、TeslaMate 4.2、Mosquitto、Home Assistant MCP、Tesla Fleet API

## Global Constraints

- Tesla FleetのVehicle Data単価は500回/$1、個人利用向け無料クレジットは月$10として計算する。
- `sensor.model_y_state`が`Online`、`Driving`、`Charging`の間だけ更新する。
- active遷移時と10分間隔で更新し、`time_pattern`の`seconds`は43とする。
- 定期更新からwake commandを呼ばない。
- `homeassistant.update_entity`の対象は`climate.model_y_climate`一つだけにする。
- Tesla Fleetの操作用entityとconfig entryを削除しない。
- Home Assistantの`.storage`ファイルを直接編集しない。
- 秘密値をcommand output、diff、ログへ出さない。
- 既存TeslaMate、Home Assistant、Mosquittoの構成を流用し、新しい依存関係を追加しない。
- ユーザーから明示されるまでcommitを作成しない。

---

### Task 1: TeslaMate MQTT discoveryをテスト先行で有効化する

**Files:**
- Modify: `roles/teslamate/tests/render_templates.yml`
- Modify: `roles/teslamate/templates/teslamate.env.j2`

**Interfaces:**
- Consumes: `teslamate_hostname=teslamate.rewse.jp`、既存Mosquitto接続変数
- Produces: `MQTT_HOME_ASSISTANT_DISCOVERY=true`と`MQTT_HOME_ASSISTANT_DISCOVERY_URL=https://teslamate.rewse.jp`を含むTeslaMate env

- [x] **Step 1: discovery envの失敗テストを追加する**

`teslamate-test : Verify TeslaMate environment contract`の`that`へ次を追加する。

```yaml
          - "'MQTT_HOME_ASSISTANT_DISCOVERY=true' in teslamate_test_env_output"
          - "'MQTT_HOME_ASSISTANT_DISCOVERY_URL=https://teslamate.rewse.jp' in teslamate_test_env_output"
```

- [x] **Step 2: REDを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: `MQTT_HOME_ASSISTANT_DISCOVERY=true`のassertがfalseになりFAILする。

- [x] **Step 3: env templateへdiscovery設定を追加する**

`MQTT_*`変数をアルファベット順に保ち、`roles/teslamate/templates/teslamate.env.j2`へ次を追加する。

```jinja2
MQTT_HOME_ASSISTANT_DISCOVERY=true
MQTT_HOME_ASSISTANT_DISCOVERY_URL=https://{{ teslamate_hostname }}
```

`MQTT_HOME_ASSISTANT_DISCOVERY_PREFIX`は追加せず、TeslaMateとHome Assistant双方の既定値`homeassistant`を使う。

- [x] **Step 4: GREENを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: `teslamate-test : Verify TeslaMate environment contract`を含む全assertがPASSする。

---

### Task 2: Tesla Fleet定期更新automationをテスト先行で追加する

**Files:**
- Create: `roles/homeassistant/tests/tesla_automation.yml`
- Create: `roles/homeassistant/files/automations-tesla.yaml`
- Modify: `roles/homeassistant/tasks/main.yml`

**Interfaces:**
- Consumes: 有効な`sensor.model_y_battery_level`、Home Assistantの`automation: !include_dir_merge_list automations/`
- Produces: `automation.refresh_tesla_fleet_data`と、その配備task

- [x] **Step 1: automation契約テストを作る**

`roles/homeassistant/tests/tesla_automation.yml`を次の内容で作る。

```yaml
---
- name: Test Tesla automation
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: "tesla-test : Parse automation"
      ansible.builtin.set_fact:
        homeassistant_tesla_automations: >-
          {{ lookup('file', '../files/automations-tesla.yaml') | from_yaml }}

    - name: "tesla-test : Verify refresh contract"
      ansible.builtin.assert:
        that:
          - homeassistant_tesla_automations | length == 1
          - homeassistant_tesla_automations[0].id == 'automation.refresh_tesla_fleet_data'
          - homeassistant_tesla_automations[0].triggers | length == 1
          - homeassistant_tesla_automations[0].triggers[0].trigger == 'time_pattern'
          - homeassistant_tesla_automations[0].triggers[0].minutes == '/30'
          - homeassistant_tesla_automations[0].triggers[0].seconds == 43
          - homeassistant_tesla_automations[0].actions | length == 1
          - homeassistant_tesla_automations[0].actions[0].action == 'homeassistant.update_entity'
          - homeassistant_tesla_automations[0].actions[0].target.entity_id == 'sensor.model_y_battery_level'
          - homeassistant_tesla_automations[0].mode == 'single'
```

- [x] **Step 2: REDを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/homeassistant/tests/tesla_automation.yml
```

Expected: `automations-tesla.yaml`が存在しないため`AnsibleError`でFAILする。

- [x] **Step 3: automationを実装する**

`roles/homeassistant/files/automations-tesla.yaml`を次の内容で作る。

```yaml
---
- id: automation.refresh_tesla_fleet_data
  alias: "Refresh Tesla Fleet Data"
  triggers:
    - trigger: time_pattern
      minutes: "/30"
      seconds: 43
  actions:
    - action: homeassistant.update_entity
      target:
        entity_id: sensor.model_y_battery_level
  mode: single
  trace:
    stored_traces: 100
```

30分ごとの更新はTesla Fleet coordinatorの`vehicle()`で無料の状態確認を行い、onlineの場合だけ`vehicle_data()`を呼ぶ。automationから`button.model_y_wake`やwake serviceは呼ばない。

- [x] **Step 4: automation copy listへ追加する**

`roles/homeassistant/tasks/main.yml`の`automation : Copy files` loopへ、アルファベット順を保って次を追加する。

```yaml
    - automations-tesla.yaml
```

配置は`automations-securities.yaml`の次とする。

- [x] **Step 5: GREENを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/homeassistant/tests/tesla_automation.yml
```

Expected: parseと全assertがPASSする。

---

### Task 3: ローカル検証とレビューを完了する

**Files:**
- Verify: `roles/teslamate/tests/render_templates.yml`
- Verify: `roles/teslamate/templates/teslamate.env.j2`
- Verify: `roles/homeassistant/tests/tesla_automation.yml`
- Verify: `roles/homeassistant/files/automations-tesla.yaml`
- Verify: `roles/homeassistant/tasks/main.yml`

**Interfaces:**
- Consumes: Task 1とTask 2の最終差分
- Produces: 本番適用可能と判断できるテスト・lint・レビュー結果

- [x] **Step 1: 対象テストをまとめて実行する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
ansible-playbook -i localhost, -c local roles/homeassistant/tests/tesla_automation.yml
```

Expected: 2つともexit code 0。

- [x] **Step 2: YAMLとAnsible構文を検証する**

Run:

```bash
ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path); puts "#{path}: OK" }' \
  roles/homeassistant/files/automations-tesla.yaml \
  roles/homeassistant/tests/tesla_automation.yml \
  roles/teslamate/tests/render_templates.yml
ansible-playbook site.yml --syntax-check
yamllint \
  roles/homeassistant/files/automations-tesla.yaml \
  roles/homeassistant/tests/tesla_automation.yml \
  roles/teslamate/tests/render_templates.yml
```

Expected: YAML parse、syntax check、yamllintがexit code 0。

- [x] **Step 3: lintと差分品質を確認する**

Run:

```bash
ansible-lint roles/teslamate roles/homeassistant/tests/tesla_automation.yml roles/homeassistant/tasks/main.yml
git -P diff --check -- \
  roles/teslamate/tests/render_templates.yml \
  roles/teslamate/templates/teslamate.env.j2 \
  roles/homeassistant/tests/tesla_automation.yml \
  roles/homeassistant/files/automations-tesla.yaml \
  roles/homeassistant/tasks/main.yml \
  .kiro/specs/teslamate-home-assistant-discovery
```

Expected: lintとdiff checkがexit code 0。既存ファイル由来のlint違反が出た場合は、変更行に新規違反がないことをbaseline比較で確認する。

- [x] **Step 4: コードレビューを実施する**

`code-reviewer`へ最終差分を渡し、次を確認する。

- MQTT discovery設定がTeslaMate 4.2の環境変数仕様と一致する。
- `time_pattern`が新構文で、`seconds: 43`を持つ。
- 更新対象が一つだけで、wake actionがない。
- 30分間隔の最大Vehicle Data費用が月$2.88である。
- 秘密値や個人情報が差分へ含まれない。

Expected: CRITICAL、HIGH、MEDIUMの未解決指摘が0件。

---

### Task 4: TeslaMate discoveryとHome Assistant automationを本番反映する

**Files:**
- Deploy: `roles/teslamate/templates/teslamate.env.j2`
- Deploy: `roles/homeassistant/files/automations-tesla.yaml`
- Deploy: `roles/homeassistant/tasks/main.yml`

**Interfaces:**
- Consumes: foxのTeslaMate、Mosquitto、Home Assistant、1Password Service Account
- Produces: MQTT discovery済みTeslaMate deviceと登録済み定期更新automation

- [x] **Step 1: 1Passwordとcheck modeを確認する**

Run:

```bash
direnv exec . op read "op://ansible/TeslaMate/encryption key" >/dev/null
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate,homeassistant_automation \
  --check --diff
```

Expected: secret lookupとcheck modeがexit code 0。diffへ秘密値が出ない。

- [x] **Step 2: TeslaMateとHome Assistant automationを適用する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate,homeassistant_automation
```

Expected: TeslaMate env変更でTeslaMate serviceが再作成され、`automations-tesla.yaml`が`/srv/homeassistant/config/automations/`へ配置される。

- [x] **Step 3: TeslaMate envを秘密値なしで確認する**

Run:

```bash
direnv exec . ansible fox.rewse.jp -b -m ansible.builtin.shell \
  -a 'docker exec teslamate printenv MQTT_HOME_ASSISTANT_DISCOVERY MQTT_HOME_ASSISTANT_DISCOVERY_URL'
```

Expected:

```text
true
https://teslamate.rewse.jp
```

- [x] **Step 4: Home Assistant設定を検証してautomationをreloadする**

Run:

```bash
mcporter call home-assistant.ha_get_system_health include=config_check
mcporter call home-assistant.ha_reload_core target=automations
mcporter call home-assistant.ha_get_state entity_id=automation.refresh_tesla_fleet_data
```

Expected: `config_check.is_valid=true`、reload成功、automation stateが`on`。

- [x] **Step 5: TeslaMate MQTT discoveryを確認する**

Run:

```bash
mcporter call home-assistant.ha_get_device integration=mqtt detail_level=full limit=200
```

Expected: `TeslaMate`由来のModel Y deviceが1件あり、state、battery level、charging、locationなどのread-only entityを持つ。既存Tesla Fleet deviceは削除されていない。

---

### Task 5: Tesla Fleet標準pollingを停止して定期更新を実機検証する

**Files:**
- Runtime state: Home Assistant Tesla Fleet config entry `pref_disable_polling`
- Runtime verification: `automation.refresh_tesla_fleet_data`

**Interfaces:**
- Consumes: Tesla Fleet config entry、Task 4で登録したautomation
- Produces: 標準polling停止状態と30分手動更新の動作証跡

- [x] **Step 1: Tesla Fleet entry IDを取得する**

Run:

```bash
entry_id="$(mcporter call home-assistant.ha_get_integration domain=tesla_fleet \
  | jq -er '.entries | select(length == 1) | .[0].entry_id')"
printf '%s\n' "$entry_id"
```

Expected: Tesla Fleet config entry IDが1件だけ出力される。

- [x] **Step 2: config entryの標準pollingを停止する**

Run:

```bash
payload="$(jq -nc --arg entry_id "$entry_id" \
  '{entry_id: $entry_id, pref_disable_polling: true}')"
mcporter call home-assistant.ha_call_service \
  ws_command=config_entries/update \
  data="$payload"
```

Expected: WebSocket commandが成功し、config entryが保持される。`.storage`ファイルは直接編集しない。

- [x] **Step 3: polling停止を確認する**

Run:

```bash
mcporter call home-assistant.ha_get_integration entry_id="$entry_id"
```

Expected: `entry.pref_disable_polling=true`かつ`entry.state=loaded`。Tesla Fleet操作用entityは引き続き存在する。

- [x] **Step 4: automationを1回だけ手動実行する**

Run:

```bash
mcporter call home-assistant.ha_call_service \
  domain=automation \
  service=trigger \
  entity_id=automation.refresh_tesla_fleet_data
mcporter call home-assistant.ha_get_state \
  entity_id=automation.refresh_tesla_fleet_data
```

Expected: actionがエラーなく完了し、`last_triggered`が現在時刻へ更新される。車両がsleep中ならTesla Fleet coordinatorは無料状態確認だけで終了し、wakeしない。

- [x] **Step 5: API上限と冪等性を最終確認する**

30分間隔の最大月額を再計算する。

```text
2 * 24 * 30 = 1,440 Vehicle Data calls
1,440 / 500 = $2.88
$10.00 - $2.88 = $7.12 remaining credit
```

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate,homeassistant_automation
```

Expected: exit code 0で、今回の設定に関するtaskは`changed=0`。最後に`git status --short`で設計・計画・実装対象以外の変更がないことを確認する。
