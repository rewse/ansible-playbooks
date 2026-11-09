# Model Y 保険走行距離警告 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保険期間（毎年 8月26日開始）内の Model Y の走行距離が、`input_number` の条件距離の 80% に達したら `binary_sensor` を on にして通知し、`dashboard-tesla` にも表示する。

**Architecture:** `utility_meter` が `sensor.model_y_odometer` を数え、cron で毎年 8月26日 0:00 にリセットする。テンプレートの binary_sensor がそれと条件距離を比べ、アラームのオートメーションが off→on で通知する。ダッシュボードは storage モードなので ha-mcp で書き換える。

**Tech Stack:** Home Assistant YAML、Ansible（`home-primary.yml`）、ha-mcp（mcporter 経由）

**Spec:** `docs/superpowers/archive/specs/2026-11-09-model-y-insurance-distance-design.md`

## Global Constraints

- utility meter: キー `model_y_insurance_distance`、`unique_id: sensor.model_y_insurance_distance`、`source: sensor.model_y_odometer`、`cron: "0 0 26 8 *"`、`periodically_resetting: false`
- input_number: `model_y_insurance_distance_limit`、単位 `km`、`mode: box`、`min: 0`
- binary_sensor: `unique_id: binary_sensor.model_y_insurance_distance_warning`、走行距離 `>=` 条件距離 `* 0.8` で on。両方が数値で条件距離が 0 より大きいときだけ available
- アラーム: id `automation.alarm_model_y_insurance_distance_warning`、`from: "off"` `to: "on"`、`notify.tats_devices`、title `"⚠ ALARM"`、メッセージに走行距離と条件距離を入れる
- ダッシュボードのタイル名は "Insurance Distance"、"Insurance Limit"、"Insurance Distance Warning"
- 作業前に `git -P fetch && git -P log --oneline HEAD..origin/main` で遅れがないか確認し、あれば fast-forward する。コミット前に `git -P status -sb` でブランチを確認する（同じクローンを別セッションが使うことがある）
- `templates.yaml` と `utility_meters.yaml` の変更は配備時に Home Assistant が再起動する。`automations-*.yaml` の配備後は `automation.reload` が必要

## Review Focus

- 条件距離が未設定（0）: binary_sensor は unavailable のままで通知しない。Task 1 のテストで availability に `> 0` があることを確かめる
- 条件距離を入れた時点ですでに 80% 以上: unavailable→on になり、`from: "off"` のため通知されない。現在 1665 km なので実害はないが、Task 2 Step 4 で on になっていないことを確認する
- Home Assistant の再起動中に on のまま: `from: "off"` で再通知しない。Task 1 のテストでトリガーを確かめる
- オドメーターが一時的に下がる・`unavailable` になる: `periodically_resetting: false` で誤加算しない。Task 1 のテストで確かめる
- 8月26日のリセット: 走行距離が 0 になり off に戻るので、翌期間も off→on で通知される。cron の値を Task 1 のテストで確かめる

---

### Task 1: 走行距離の計測と警告

**Files:**
- Modify: `roles/homeassistant/files/utility_meters.yaml`（末尾に空行で区切って追加）
- Modify: `roles/homeassistant/files/input_numbers.yaml`（`# Mom’s Room` の前に `# Model Y` 節を追加）
- Modify: `roles/homeassistant/files/templates.yaml`（`# Model Y` 節の `binary_sensor.model_y_battery_full_charge_due` の後ろ）
- Modify: `roles/homeassistant/files/automations-alarm.yaml`（`automation.alarm_model_y_battery_full_charge_due` の後ろ）
- Create: `roles/homeassistant/tests/model_y_insurance_distance.yml`

**Interfaces:**
- Produces: `sensor.model_y_insurance_distance`（km）、`input_number.model_y_insurance_distance_limit`、`binary_sensor.model_y_insurance_distance_warning`、`automation.alarm_model_y_insurance_distance_warning`

- [ ] **Step 1: テストを書く**

`model_y_full_charge_due.yml` と同じ形式で、`utility_meters.yaml`、`input_numbers.yaml`、`templates.yaml`、`automations-alarm.yaml` を読み込み、次を assert する。`homeassistant_warning_sensors` は `templates.yaml` の binary_sensor から unique_id で、`homeassistant_alarm_automations` は id で絞り込む。

```yaml
- homeassistant_utility_meters.model_y_insurance_distance.unique_id == 'sensor.model_y_insurance_distance'
- homeassistant_utility_meters.model_y_insurance_distance.source == 'sensor.model_y_odometer'
- homeassistant_utility_meters.model_y_insurance_distance.cron == '0 0 26 8 *'
- homeassistant_utility_meters.model_y_insurance_distance.periodically_resetting == false
- "'cycle' not in homeassistant_utility_meters.model_y_insurance_distance"
- homeassistant_input_numbers.model_y_insurance_distance_limit.min == 0
- homeassistant_input_numbers.model_y_insurance_distance_limit.unit_of_measurement == 'km'
- homeassistant_input_numbers.model_y_insurance_distance_limit.mode == 'box'
- homeassistant_warning_sensors | length == 1
- "'sensor.model_y_insurance_distance' in homeassistant_warning_sensors[0].availability"
- "'input_number.model_y_insurance_distance_limit' in homeassistant_warning_sensors[0].availability"
- "'> 0' in homeassistant_warning_sensors[0].availability"
- "'0.8' in homeassistant_warning_sensors[0].state"
- homeassistant_alarm_automations | length == 1
- >-
  homeassistant_alarm_automations[0].triggers
  == [{'trigger': 'state', 'entity_id': 'binary_sensor.model_y_insurance_distance_warning', 'from': 'off', 'to': 'on'}]
- homeassistant_alarm_automations[0].actions[0].action == 'notify.tats_devices'
- homeassistant_alarm_automations[0].actions[0].data.title == '⚠ ALARM'
- homeassistant_alarm_automations[0].trace.stored_traces == 100
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_insurance_distance.yml`
Expected: FAIL（キーや要素が見つからない）

- [ ] **Step 3: 実装する**

utility meter と input_number を Global Constraints の値で追加する（input_number の name は `"Model Y Insurance Distance Limit"`、`max`、`step`、icon は実装者が決める）。utility meter の直前に、期間の区切りと `periodically_resetting: false` の理由（オドメーターは減らないので、一時的な低下をリセットと見なして全体を加算しないため）を書く。binary_sensor の name は `"Model Y Insurance Distance Warning"`、直前のコメントは「保険期間内の走行距離が条件の 80% に達すると on になる」という内容にする。アラームの alias は `"ALARM: Model Y Insurance Distance Warning"`、トリガーの前に既存と同じ「off から始めることで再起動時に通知を繰り返さない」コメントを付け、メッセージは `states()` で走行距離と条件距離を入れる。

- [ ] **Step 4: テストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_insurance_distance.yml roles/homeassistant/tests/model_y_full_charge_due.yml roles/homeassistant/tests/utility_meter_cost_charts.yml`
Expected: `failed=0`

- [ ] **Step 5: リントとテスト一式を通してコミットする**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`（新規ファイルは先に `git add`）と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも成功

```bash
git add roles/homeassistant/files/utility_meters.yaml roles/homeassistant/files/input_numbers.yaml roles/homeassistant/files/templates.yaml roles/homeassistant/files/automations-alarm.yaml roles/homeassistant/tests/model_y_insurance_distance.yml
git commit -m "feat(homeassistant): warn when the Model Y nears its insurance distance limit"
```

### Task 2: 配備と初期値

**Files:** なし

**Interfaces:**
- Consumes: Task 1 の全エンティティ

- [ ] **Step 1: 差分を確認する**

Run: `ansible-playbook home-primary.yml --tags homeassistant_configuration,homeassistant_automation --check --diff`
Expected: 終了コード 0。差分が Task 1 の 4 ファイルだけ

- [ ] **Step 2: 配備する**

Run: Step 1 から `--check` を外して実行し、Home Assistant の再起動を待ってから ha-mcp の `ha_call_service` で `automation.reload` を呼ぶ
Expected: 終了コード 0。`sensor.model_y_insurance_distance`、`input_number.model_y_insurance_distance_limit`、`binary_sensor.model_y_insurance_distance_warning`（unavailable）、`automation.alarm_model_y_insurance_distance_warning` が存在する

- [ ] **Step 3: 走行距離を較正する**

`sensor.model_y_odometer` の現在値を読み、`utility_meter.calibrate`（`entity_id: sensor.model_y_insurance_distance`、`value: <その値>`）を呼ぶ。今の保険期間は 0 km から始まっているので、値はそのまま使う。
Expected: `sensor.model_y_insurance_distance` がオドメーターと同じ値になる

- [ ] **Step 4: 条件距離を入れる**

利用者に条件距離（km）を尋ね、`input_number.set_value` で入れる。
Expected: `binary_sensor.model_y_insurance_distance_warning` が `off`（走行距離が条件の 80% 未満の場合）

### Task 3: ダッシュボードと push

**Files:** なし（`dashboard-tesla` は storage モード）

**Interfaces:**
- Consumes: Task 1 の 3 エンティティ

- [ ] **Step 1: タイルを追加する**

`MCPORTER_KEEPALIVE=home-assistant` を付けて `ha_config_get_dashboard url_path=dashboard-tesla` で設定と `config_hash` を得る。`model-y` ビューの最初のセクションで、`entity: sensor.model_y_last_seen` のタイルの直後に次の 3 枚を挿入し、`ha_config_set_dashboard` で保存する。他のカードは変えない。各タイルは既存タイルと同じく `features_position: bottom`、`vertical: false`、`state_content: [state, last_changed]` を持つ。

- `sensor.model_y_insurance_distance`、name `"Insurance Distance"`、`grid_options: {columns: 6, rows: 1}`
- `input_number.model_y_insurance_distance_limit`、name `"Insurance Limit"`、`grid_options: {columns: 6, rows: 1}`
- `binary_sensor.model_y_insurance_distance_warning`、name `"Insurance Distance Warning"`、`grid_options: {columns: 12, rows: 1}`、`visibility: [{condition: state, entity: binary_sensor.model_y_insurance_distance_warning, state: "on"}]`

- [ ] **Step 2: 確認する**

Run: `ha_config_get_dashboard url_path=dashboard-tesla` の出力を `rg -c "insurance_distance"` で数える
Expected: 4 件（警告タイルの `entity` と `visibility` で 2 件）。さらに利用者の Chrome（agent-browser、CDP）で `https://hass.rewse.jp/dashboard-tesla/model-y` を開き、"Odometer" の下に "Insurance Distance" と "Insurance Limit" が出ていて、警告タイルが見えないことを確認する

- [ ] **Step 3: 仕様と計画をアーカイブして push する**

`git mv` で spec と plan を `docs/superpowers/archive/specs/`、`docs/superpowers/archive/plans/` に移し、plan 内の Spec のパスを直してコミットする。

```bash
git commit -m "docs: archive Model Y insurance distance spec and plan"
git -P push
```

Expected: push 成功
