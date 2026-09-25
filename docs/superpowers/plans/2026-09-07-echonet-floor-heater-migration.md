# ECHONET Lite床暖房移行 Implementation Plan

> **For agentic workers:** 承認済み設計に従い、各チェック項目を順番に実行する。

**Goal:** 旧床面温度差推定・旧SwitchBotスイッチ・旧groupを廃止し、床暖房制御と表示をECHONET Lite operation statusスイッチへ統一する。

**Architecture:** リポジトリでは新しい2スイッチを自動化、スクリプト、Alexaの参照先にする。旧YAMLエンティティとswitch includeを削除し、storage-modeダッシュボードはconfig hash付きのHome Assistant API更新で対象カードだけ変更する。

**Tech Stack:** Ansible、Home Assistant 2026.8、YAML、Home Assistant MCP

## Global Constraints

- `switch.living_room_floor_heater_operation_status`と`switch.study_floor_heater_operation_status`を制御対象にする。
- オン条件は片方でもオフなら成立し、両方をオンにする。
- オフ条件は片方でもオンなら成立し、両方をオフにする。
- `binary_sensor.living_room_temp_high`の1時間待機は維持する。
- 床暖房スイッチ状態に対する1時間待機は使用しない。
- Alexaにはliving room側だけを公開する。
- Matterデバイス本体は削除しない。
- 床暖房を実際に操作する自動テストは行わない。
- コミットは明示された場合だけ作成する。

---

### Task 1: リポジトリ設定をテストファーストで移行する

**Files:**
- Create: `roles/homeassistant/tests/echonet_floor_heater_migration.yml`
- Delete: `roles/homeassistant/files/switches.yaml`
- Modify: `roles/homeassistant/files/alexa.yaml`
- Modify: `roles/homeassistant/files/automations-alarm.yaml`
- Modify: `roles/homeassistant/files/automations-living-room-climates.yaml`
- Modify: `roles/homeassistant/files/customize.yaml`
- Modify: `roles/homeassistant/files/scripts.yaml`
- Modify: `roles/homeassistant/files/templates.yaml`
- Modify: `roles/homeassistant/tasks/main.yml`

**Interfaces:**
- Consumes: ECHONET Lite operation statusスイッチ2件と既存同期自動化
- Produces: 旧5エンティティとFloor Thermometer派生参照を含まないHome Assistant YAML

- [x] **Step 1: 失敗する契約テストを作成する**

テストは対象ファイルを読み込み、次を検査する。

```yaml
- roles/homeassistant/files/switches.yamlが存在しない
- 旧5エンティティの定義と利用が対象YAMLに存在しない
- toggle_living_area_floor_heatingのオン・オフ分岐がmatch: anyで新2スイッチを判定する
- toggle_living_area_floor_heatingが新2スイッチを同時にturn_on/turn_offする
- living_room_temp_highのfor.hours == 1を維持する
- toggle_living_room_ac_heatの床暖房条件がmatch: anyでforを持たない
- Darken Living Roomが片方でもonなら新2スイッチをturn_offする
- Alexaがliving room側だけを公開する
- Floor Thermometerのbattery・connectivityアラーム参照が存在しない
- tasks/main.ymlにswitch includeとswitches.yamlの追加・削除タスクが存在しない
```

- [x] **Step 2: REDを確認する**

Run: `ansible-playbook roles/homeassistant/tests/echonet_floor_heater_migration.yml`
Expected: 旧設定が残っているassertでexit code 2になる。

- [x] **Step 3: 最小実装を行う**

自動化の状態条件は次の形に統一する。

```yaml
- condition: state
  entity_id:
    - switch.living_room_floor_heater_operation_status
    - switch.study_floor_heater_operation_status
  match: any
  state: "off"
```

操作は次の形で両方を対象にする。

```yaml
- action: switch.turn_on
  target:
    entity_id:
      - switch.living_room_floor_heater_operation_status
      - switch.study_floor_heater_operation_status
```

switch include行と`/srv/homeassistant/config/switches.yaml`の削除は、一回限りの移行処理としてfoxへSSHで実行する。

```bash
ssh -p 11022 ubuntu@fox.rewse.jp \
  "sudo sed -i '/^switch:/d' /srv/homeassistant/config/configuration.yaml && \
   sudo rm -f /srv/homeassistant/config/switches.yaml"
```

Ansible playbookには削除タスクを追加しない。`template : Configure include`の`insertafter`だけを`'^shell_command:'`にする。

- [x] **Step 4: GREENを確認する**

Run: `ansible-playbook roles/homeassistant/tests/echonet_floor_heater_migration.yml`
Expected: 全assertが成功し、exit code 0になる。

Run: `ansible-playbook roles/homeassistant/tests/floor_heater_operation_status_sync.yml`
Expected: 既存同期自動化の全assertが成功し、exit code 0になる。

Run: `rg -n "living_area_floor_heatings|living_room_floor_heating\\b|study_floor_heating\\b|living_room_floor_heating_effect|floor_thermometer_connectivity|floor_thermometer_battery|switches.yaml|switch: !include" roles/homeassistant --glob '!tests/**'`
Expected: 廃止対象の実利用が0件になる。

### Task 2: ダッシュボードをconfig hash付きで移行する

**Resources:**
- Modify: Home Assistant dashboard `dashboard-climate`
- Modify: Home Assistant dashboard `lovelace`

**Interfaces:**
- Consumes: storage-mode Lovelace configと現在のconfig hash
- Produces: 旧groupカード0件、旧個別スイッチカード0件、effect履歴カード0件

- [x] **Step 1: 現在設定とconfig hashを取得する**

`ha_config_get_dashboard`で各dashboardを取得し、書き込み直前のhashを使う。旧group、旧個別スイッチ、effect sensorの検索結果を更新前証拠として保存する。

- [x] **Step 2: 対象カードだけを原子的に変更する**

`ha_config_set_dashboard`へ現在の`config_hash`と`python_transform`を渡し、次を1dashboardにつき1回のwriteで行う。

```text
entity == switch.living_area_floor_heatingsのカードを削除
entity == switch.living_room_floor_heatingをliving_room operation statusへ置換
entity == switch.study_floor_heatingをstudy operation statusへ置換
sensor.living_room_floor_heating_effectだけを含むhistory-graphカードを削除
```

hash不一致では再取得し、差分を確認するまで再試行しない。

- [x] **Step 3: 更新結果を検索で確認する**

旧4 entity queryのdashboard matchが0件、新2 switch queryがそれぞれ3件であることを確認する。

### Task 3: foxへ配備して実環境を検証する

**Resources:**
- Deploy: Home Assistant role to `fox.rewse.jp`
- Reload: Home Assistant automations、scripts、templates、Alexa関連設定

**Interfaces:**
- Consumes: Task 1のGREEN設定とTask 2のdashboard更新
- Produces: 旧エンティティが存在せず、新ECHONET Lite経路が有効な実環境

- [x] **Step 1: 構文とcheck modeを検証する**

Run: `ansible-playbook singleton_int1.yml --syntax-check`
Expected: exit code 0。

Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant --check --diff`
Expected: 対象設定の置換・削除だけが報告され、exit code 0。

- [x] **Step 2: foxへ適用する**

Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant`
Expected: process exit code 0。handlerによる再起動が発生した場合はHome Assistant復帰まで待つ。

- [x] **Step 3: Home Assistant設定とentityを検証する**

`ha_get_system_health(include="config_check")`がvalidであることを確認する。旧5エンティティが存在せず、新2スイッチ、同期自動化、toggle自動化が有効であることを確認する。Matterデバイスと直接entity 7件は残っていることを確認する。

- [x] **Step 4: 参照残りと実機非操作を確認する**

リポジトリとHome Assistant検索でFloor Thermometerおよび旧スイッチ参照を再確認する。新2スイッチの`last_changed`が検証作業で変化していないことを確認する。
