# 副センサー欠測からの即時復旧 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3 部屋の温度計・湿度計 fault を「遅延付きの anomaly」と「遅延なしの副センサー欠測」の OR に分け、副センサー復帰と同時に自動 Climate 制御を再開させる。

**Architecture:** `roles/homeassistant/files/templates.yaml` に `binary_sensor.<room>_thermometer_anomaly` と `binary_sensor.<room>_hygrometer_anomaly` を追加し、既存 fault から値の異常条件と `delay_off` を移す。既存 fault は anomaly と副センサーの 24 時間条件だけを見る。entity ID を変えないので automation とアラームは触らない。

**Tech Stack:** Home Assistant template binary sensor、Ansible（localhost の構造テスト playbook）

**Spec:** `docs/superpowers/specs/2026-10-25-secondary-sensor-fault-recovery-design.md`

## Global Constraints

- 対象 room prefix: `dads_room`、`living_room`、`moms_room`
- 副センサー: `sensor.dads_room_switchbot_meter_*`、`sensor.living_room_switchbot_hub_2_*`、`sensor.moms_room_switchbot_meter_*`
- しきい値は変えない: 温度 `< 5` / `> 40`、湿度 `< 1` / `> 99`、主センサー未報告 `>= 7200`、副センサー欠測・未報告 `>= 86400`
- anomaly: `delay_off: hours: 1`、`device_class: problem`、name は既存 fault の `Fault` を `Anomaly` に置換（例: `Dad’s Room Thermometer Anomaly`）
- fault: `delay_off` なし、`device_class: problem`、unique_id と name は現状維持
- `automations-*.yaml` は変更しない
- コメントは英語で、現在の挙動を書く（変更履歴は書かない）

## Review Focus

- anomaly が `unavailable` や `unknown` のとき、fault は `is_state(anomaly, 'on')` が偽になり off になる。anomaly は同じ `templates.yaml` の template entity で単独では壊れにくいので、この fail-open を受け入れる。`not is_state(anomaly, 'off')` にすると起動時に fault が一瞬 on になり、アラームが誤通知する。Task 1 と 2 のテストで `is_state('<anomaly>', 'on')` の形を固定する。
- 副センサー復帰直後に範囲外や disagreement が真なら、fault は anomaly 経由で on を保つ必要がある。範囲外チェックと disagreement が anomaly にあることをテストで固定する。
- 副センサーの 24 時間条件が anomaly に残ると即時復旧にならない。anomaly に `86400` と `.last_changed` が無いことをテストで固定する。
- 主センサーの 2 時間未報告条件が fault に残ると遅延なしで解除され、ばたつく。fault に `7200` が無いことをテストで固定する。
- `templates.yaml` は再起動が必要な設定ファイル（`homeassistant_config_files`）なので、適用で Home Assistant が再起動する。Task 3 で再起動後のアラーム誤通知とテンプレートエラーの有無を確認する。

---

### Task 1: 温度計 fault の分割

**Files:**
- Modify: `roles/homeassistant/tests/thermometer_fault_detection.yml`
- Modify: `roles/homeassistant/tests/thermometer_fault_detection_room.yml`
- Modify: `roles/homeassistant/files/templates.yaml`（3 部屋の `*_thermometer_fault`、各部屋に `*_thermometer_anomaly` を追加）

**Interfaces:**
- Produces: `binary_sensor.dads_room_thermometer_anomaly`、`binary_sensor.living_room_thermometer_anomaly`、`binary_sensor.moms_room_thermometer_anomaly`

- [ ] **Step 1: 現状のテストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/thermometer_fault_detection.yml`
Expected: exit 0

- [ ] **Step 2: テストの契約を新構造に書き換える**

`thermometer_fault_detection.yml` の各 room_contract に `anomaly_entity_id: binary_sensor.<prefix>_thermometer_anomaly` と `primary_entity_id: sensor.<prefix>_temperature` を追加する。

`thermometer_fault_detection_room.yml` で anomaly を `homeassistant_test_room_anomaly_sensor` として選び、存在数 1 を assert する。「Verify persistence」「Verify source freshness」「Verify secondary availability delay」を次の assert に置き換える。

anomaly:
- `delay_off.hours == 1`、`device_class == 'problem'`
- `regex_findall('not is_number') | length == 1`
- `primary \\| float < 5`、`primary \\| float > 40`、`secondary \\| float < 5`、`secondary \\| float > 40` がそれぞれ 1 回
- `regex_findall('>= 7200') | length == 1`
- `('states.' ~ room_contract.primary_entity_id ~ '.last_reported') in state`
- `("is_state('binary_sensor." ~ room_contract.prefix ~ "_temperature_disagreement', 'on')") in state`
- `'86400' not in state`、`'.last_changed' not in state`

fault:
- `'delay_off' not in homeassistant_test_room_fault_sensor`、`device_class == 'problem'`
- `("is_state('" ~ room_contract.anomaly_entity_id ~ "', 'on')") in state`
- 既存と同じ空白正規化で、`not is_number(secondary) and (now() - states.<secondary>.last_changed).total_seconds() >= 86400` と `is_number(secondary) and (now() - states.<secondary>.last_reported).total_seconds() >= 86400` を含む
- `'7200' not in state`、`'float <' not in state`、`'disagreement' not in state`

`secondary_unavailable_seconds is not defined` の分岐は fault を対象にしたまま残す。「Verify smoothed wiring」「Verify alarm」「Verify control guards」は変更しない。

- [ ] **Step 3: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/thermometer_fault_detection.yml`
Expected: FAIL（anomaly sensor の存在数が 0）

- [ ] **Step 4: `templates.yaml` を変更する**

3 部屋それぞれで、既存 `*_thermometer_fault` の state と `delay_off` を新しい `*_thermometer_anomaly` へ移し、副センサー 24 時間条件の 2 節だけを anomaly から除く。anomaly は `*_thermometer_connectivity` の直前に置き、コメント `# Detects abnormal readings; clears after one hour of normal readings.` を付ける。

fault のコメントを `# Combines reading anomalies with secondary sensor outages, which clear immediately.` に替え、state を次の形にする（部屋ごとに entity を置換）。

```yaml
    state: >-
      {% set secondary = states('sensor.dads_room_switchbot_meter_temperature') %}
      {{
        is_state('binary_sensor.dads_room_thermometer_anomaly', 'on') or
        (
          not is_number(secondary) and
          (now() - states.sensor.dads_room_switchbot_meter_temperature.last_changed).total_seconds() >= 86400
        ) or
        (
          is_number(secondary) and
          (now() - states.sensor.dads_room_switchbot_meter_temperature.last_reported).total_seconds() >= 86400
        )
      }}
    device_class: problem
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/thermometer_fault_detection.yml`
Expected: exit 0、failed=0

- [ ] **Step 6: Commit**

```bash
git add roles/homeassistant/files/templates.yaml roles/homeassistant/tests/thermometer_fault_detection.yml roles/homeassistant/tests/thermometer_fault_detection_room.yml
git commit -m "fix(homeassistant): clear thermometer faults as soon as secondary sensors return"
```

### Task 2: 湿度計 fault の分割

**Files:**
- Modify: `roles/homeassistant/tests/hygrometer_fault_detection.yml`
- Modify: `roles/homeassistant/tests/hygrometer_fault_detection_room.yml`
- Modify: `roles/homeassistant/files/templates.yaml`（3 部屋の `*_hygrometer_fault`、各部屋に `*_hygrometer_anomaly` を追加）

**Interfaces:**
- Produces: `binary_sensor.dads_room_hygrometer_anomaly`、`binary_sensor.living_room_hygrometer_anomaly`、`binary_sensor.moms_room_hygrometer_anomaly`

Task 1 と同じ手順で進める。違いは次のとおり。

- contract に `anomaly_entity_id: binary_sensor.<prefix>_hygrometer_anomaly` と `primary_entity_id: sensor.<prefix>_humidity` を追加する
- 範囲のしきい値は `< 1` と `> 99`、disagreement は `binary_sensor.<prefix>_humidity_disagreement`
- anomaly は `*_hygrometer_fault` の直前に置く
- テスト: `ansible-playbook roles/homeassistant/tests/hygrometer_fault_detection.yml`
- コミット: `fix(homeassistant): clear hygrometer faults as soon as secondary sensors return`

### Task 3: 検証と適用

**Files:** なし（Task 1 と 2 の成果物を検証して適用する）

- [ ] **Step 1: リポジトリ全体の検証を流す**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも exit 0。フックが整形したファイルがあればコミットする。

- [ ] **Step 2: check mode で確認する**

`git fetch` で origin と揃っていることを確かめてから実行する。
Run: `ansible-playbook home-primary.yml --tags homeassistant_configuration --check --diff`
Expected: exit 0、差分は `templates.yaml` の 6 entity 追加と 6 fault の変更だけ

- [ ] **Step 3: ユーザーの承認を得て適用する**

適用すると Home Assistant が再起動するので、承認後に実行する。
Run: `ansible-playbook home-primary.yml --tags homeassistant_configuration`
Expected: exit 0

- [ ] **Step 4: 実機で確認する**

`mcporter call home-assistant.ha_get_state` で 6 個の anomaly と 6 個の fault を読み、全て存在し、値の異常がなければ `off` であることを確認する。`ha_get_logs source=logbook` で再起動直後に `ALARM:` の温湿度差アラームが出ていないこと、`ha_get_logs source=error_log search=template` で新しいテンプレートエラーが無いことを確認する。
