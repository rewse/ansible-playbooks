# 温湿度計 anomaly の一時欠測への耐性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 主センサーの 10 分未満の欠測では anomaly と fault が on にならず、条件が解消したらすぐ off になるようにする。

**Architecture:** 3 部屋の anomaly（6 個）から範囲外の判定と `delay_off` を消し、非数値の判定だけテンプレート内で `last_changed` から 10 分待つ。disagreement（6 個）は `delay_on` を 1 時間にする。fault は変えない。

**Tech Stack:** Home Assistant template binary_sensor、Ansible のテスト playbook（`roles/homeassistant/tests/*_fault_detection*.yml`）

**Spec:** `docs/superpowers/specs/2026-10-25-sensor-anomaly-transient-tolerance-design.md`

## Global Constraints

- 対象は Dad’s Room、Living Room、Mom’s Room の `binary_sensor.<room>_thermometer_anomaly`、`_hygrometer_anomaly`、`_temperature_disagreement`、`_humidity_disagreement` の 12 個だけ。fault、アラーム、Climate 制御 automation、平滑化センサーは変えない
- anomaly の state は次の 3 条件の OR で、`delay_on` も `delay_off` も持たない
  - `not is_number(primary) and (now() - states.<primary>.last_changed).total_seconds() >= 600`
  - `(now() - states.<primary>.last_reported).total_seconds() >= 7200`
  - `is_state('binary_sensor.<room>_<temperature|humidity>_disagreement', 'on')`
- 範囲外の判定（温度 `< 5`、`> 40`、湿度 `< 1`、`> 99`）と、それだけに使う `secondary` 変数を消す
- disagreement は `delay_on: hours: 1` で、`delay_off` を持たない。しきい値 1.5 と 10 は変えない
- 主センサーは温度が `sensor.<room>_temperature`、湿度が `sensor.<room>_humidity`
- コメントは英語で、今の挙動を書く
- `roles/homeassistant/files/` は lint の対象外。テストは `uv run --with ansible-core ansible-playbook roles/homeassistant/tests/thermometer_fault_detection.yml` と `hygrometer_fault_detection.yml` で動かす
- push と fox への反映は実施の前にユーザーの確認を取る。反映は HA を再起動する

## Review Focus

- `last_changed` 判定は、主センサーが数値に戻ったら即座に偽になる必要がある。`not is_number(primary) and` が時刻比較の前にあることを Task 1 のテストで固定する
- disagreement を 1 時間にしても anomaly 側に遅延が残ると意味がない。anomaly に `delay_on` と `delay_off` がないことを Task 1 のテストで固定する
- 範囲外の判定が 1 部屋だけ残ると部屋ごとに挙動が分かれる。3 部屋の契約で `float <` と `float >` が anomaly にないことを Task 1 のテストで固定する
- HA の起動直後は主センサーの `last_changed` が起動時刻になる。10 分以内に Matter が戻れば anomaly が on にならないことを Task 2 の実機確認で見る
- disagreement の `delay_off` がなくなると、しきい値近くでのばたつきで通知が増えうる。ユーザーは起きてから調整すると決めたので、テストでは固定しない

---

### Task 1: anomaly と disagreement の遅延と条件を変える

**Files:**
- Modify: `roles/homeassistant/files/templates.yaml`（12 個のセンサー）
- Test: `roles/homeassistant/tests/thermometer_fault_detection_room.yml`、`roles/homeassistant/tests/hygrometer_fault_detection_room.yml`

**Interfaces:**
- Produces: entity ID は変わらない

- [ ] **Step 1: テストの契約を新しい形にする**

両方の `*_room.yml` の `Verify anomaly persistence` の `that:` を次に置き換える。既存の `'.last_changed' not in` の行は消える。湿度側は `temperature` を `humidity`、`'> 1.5'` を `'> 10'` にする（`primary_entity_id` は両方の契約にすでにある）。

```yaml
      - homeassistant_test_room_disagreement_sensor.delay_on.hours == 1
      - "'delay_off' not in homeassistant_test_room_disagreement_sensor"
      - "'delay_on' not in homeassistant_test_room_anomaly_sensor"
      - "'delay_off' not in homeassistant_test_room_anomaly_sensor"
      - homeassistant_test_room_anomaly_sensor.device_class == 'problem'
      - "'> 1.5' in homeassistant_test_room_disagreement_sensor.state"
      - >-
        (
          "not is_number(primary) and (now() - states." ~
          room_contract.primary_entity_id ~
          ".last_changed).total_seconds() >= 600"
        ) in (homeassistant_test_room_anomaly_sensor.state | regex_replace('\\s+', ' '))
      - "'float <' not in homeassistant_test_room_anomaly_sensor.state"
      - "'float >' not in homeassistant_test_room_anomaly_sensor.state"
      - "'secondary' not in homeassistant_test_room_anomaly_sensor.state"
      - homeassistant_test_room_anomaly_sensor.state | regex_findall('>= 7200') | length == 1
      - "('states.' ~ room_contract.primary_entity_id ~ '.last_reported') in homeassistant_test_room_anomaly_sensor.state"
      - >-
        ("is_state('binary_sensor." ~ room_contract.prefix ~
         "_temperature_disagreement', 'on')") in homeassistant_test_room_anomaly_sensor.state
      - "'86400' not in homeassistant_test_room_anomaly_sensor.state"
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with ansible-core ansible-playbook roles/homeassistant/tests/thermometer_fault_detection.yml roles/homeassistant/tests/hygrometer_fault_detection.yml`
Expected: `Verify anomaly persistence` で失敗する（`delay_on.hours` が 2）

- [ ] **Step 3: templates.yaml を変える**

12 個のセンサーを Global Constraints のとおりにする。anomaly のコメントは、10 分続いた欠測、2 時間の未報告、disagreement で on になり、解消したらすぐ off になる、という趣旨にする。

- [ ] **Step 4: 通ることを確かめる**

Run: Step 2 と同じ
Expected: 両方とも `failed=0`

Run: `uv run --with pytest --with ansible-core pytest tests -q` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: 全件 PASS、全フック Passed

- [ ] **Step 5: コミット**

```bash
git add roles/homeassistant/files/templates.yaml roles/homeassistant/tests/
git commit -m "fix(homeassistant): ride out brief sensor outages without raising faults"
```

### Task 2: 反映と実機確認

- [ ] **Step 1: 反映前の確認**

`mcporter call home-assistant.ha_eval_template` で副センサー 6 個（`sensor.<room>_switchbot_meter_temperature` と `_humidity`、Living Room は `sensor.living_room_switchbot_hub_2_*`）が数値であることと、12 個の anomaly と fault が off であることを確かめる。

- [ ] **Step 2: push と check**

ユーザーの確認後に push し、`git -P fetch && git -P log --oneline HEAD..origin/main` が空であることを確かめる。
Run: `direnv exec . ansible-playbook home-primary.yml --tags homeassistant_configuration --check --diff`
Expected: 終了コード 0、`templates.yaml` の差分だけ

- [ ] **Step 3: 反映**

Run: `direnv exec . ansible-playbook home-primary.yml --tags homeassistant_configuration --diff`
Expected: 終了コード 0、HA が再起動する

- [ ] **Step 4: 実機確認**

再起動から 15 分後に、12 個の anomaly と fault が off のままで、`last_changed` が再起動の前後で変わっていないか、変わっても off であることを確かめる。ユーザーにアラーム通知が来ていないか確かめてもらう。

Run: `direnv exec . ansible-playbook home-primary.yml --tags homeassistant_configuration --check --diff`
Expected: 終了コード 0、`changed=0`
