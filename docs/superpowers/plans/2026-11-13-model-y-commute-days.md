# Model Y 通勤日数警告 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 直近30日に Model Y が通勤先の駐車場に入った日数を数え、12日と14日に達したら通知し、`dashboard-tesla` にも表示する。

**Architecture:** `templates.yaml` の trigger 型ブロックが、ジオフェンスの変化・毎日 0:00・起動・初期値イベントで再計算し、通勤した日付のリストを属性 `dates` に持つ。2つの binary_sensor がその件数をしきい値と比べ、アラームのオートメーションが off→on で通知する。ダッシュボードは storage モードなので ha-mcp で書き換える。

**Tech Stack:** Home Assistant YAML（trigger-based template）、Ansible（`home-primary.yml`）、ha-mcp（mcporter 経由）

**Spec:** `docs/superpowers/specs/2026-11-13-model-y-commute-days-design.md`

## Global Constraints

- 通勤先の駐車場（小文字で比較）: `apa hotel & resort roppongi ekihigashi`、`ark hills sengokuyama mori tower`、`tns azabudai 3-chome`
- sensor: `unique_id: sensor.model_y_commute_days`、name `"Model Y Commute Days"`、状態は `dates` の件数、属性 `dates` は `YYYY-MM-DD` 文字列の昇順リスト（重複なし、今日から29日前以降）
- 日付の追加条件: ジオフェンスが通勤先のどれかで、かつ `as_local(states.sensor.model_y_geofence.last_changed).date() == now().date()`
- トリガー: `sensor.model_y_geofence` の state（`to: null`）、`time` `at: "00:00:00"`、`homeassistant` `event: start`、`event` `event_type: model_y_commute_days_set`（`id: set`。`trigger.event.data.dates` でリストを置き換える）
- binary_sensor: `unique_id: binary_sensor.model_y_commute_days_80_percent`（`>= 15 * 0.8`）と `binary_sensor.model_y_commute_days_90_percent`（`>= 15 * 0.9`）。どちらも `sensor.model_y_commute_days` が数値のときだけ available
- アラーム: id `automation.alarm_model_y_commute_days_warning`、2つの binary_sensor の `from: "off"` `to: "on"`、`notify.tats_devices`、title `"⚠️ ALARM"`（U+FE0F 付き）、メッセージに通勤日数と達したしきい値
- ダッシュボードのタイル名は "Commute Days"、"Commute Days 80%"、"Commute Days 90%"
- 作業前に `git -P fetch && git -P log --oneline HEAD..origin/main` で遅れがないか確認し、あれば fast-forward する。コミット前に `git -P status -sb` でブランチを確認する（同じクローンを別セッションが使うことがある）
- `templates.yaml` の変更は配備時に Home Assistant が再起動する。`automations-*.yaml` の配備後は `automation.reload` が必要

## Review Focus

- 同じ日に何度も出入りする（11/12 は APA に 9:35 と 18:38）: 1日として数える。Task 2 Step 3 で、同じ日付の2回目の到着で件数が増えないことを確かめる
- 前日から通勤先に停めたまま 0:00 を迎える: 翌日を数えない。Task 1 のテストで `last_changed` 条件があることを、Task 2 Step 3 で 0:00 相当の評価で今日が足されないことを確かめる
- Home Assistant の再起動: 属性 `dates` が復元され、件数が0に戻らない。Task 2 Step 5 で再起動前後の `dates` を比べる
- ジオフェンス名の大文字小文字の違い: `lower` で比べる。Task 1 のテストで `| lower` があることを確かめる
- 初期値の流し込みで一気に14日以上になる: 両方の binary_sensor が off→on になり、通知が2通届く。Task 2 Step 4 で通知の有無を利用者に伝える

---

### Task 1: 通勤日数の計測と警告

**Files:**
- Modify: `roles/homeassistant/files/templates.yaml`（末尾に trigger 型ブロックを追加）
- Modify: `roles/homeassistant/files/automations-alarm.yaml`（`automation.alarm_model_y_insurance_distance_warning` の後ろ）
- Create: `roles/homeassistant/tests/model_y_commute_days.yml`

**Interfaces:**
- Produces: `sensor.model_y_commute_days`（属性 `dates`）、`binary_sensor.model_y_commute_days_80_percent`、`binary_sensor.model_y_commute_days_90_percent`、`automation.alarm_model_y_commute_days_warning`、イベント `model_y_commute_days_set`（data `dates: [YYYY-MM-DD, ...]`）

- [ ] **Step 1: テストを書く**

`model_y_insurance_distance.yml` と同じ形式で `templates.yaml` と `automations-alarm.yaml` を読み込む。trigger 型ブロックは `homeassistant_template_groups | selectattr('triggers', 'defined') | selectattr('sensor', 'defined')` のうち、`sensor` に `unique_id: sensor.model_y_commute_days` を含むものとして `homeassistant_commute_groups` に絞り込む。そのブロックの `sensor[0]` を `homeassistant_commute_sensor`、`binary_sensor` を unique_id で引いたものを `homeassistant_commute_80` と `homeassistant_commute_90`、ブロックの `variables` と全テンプレートを `to_json` で連結した文字列を `homeassistant_commute_text` とする。アラームは id で `homeassistant_alarm_automations` に絞り込む。次を assert する。

```yaml
- homeassistant_commute_groups | length == 1
- >-
  homeassistant_commute_groups[0].triggers
  | selectattr('trigger', 'equalto', 'state') | list
  == [{'trigger': 'state', 'entity_id': 'sensor.model_y_geofence', 'to': None}]
- >-
  homeassistant_commute_groups[0].triggers
  | selectattr('trigger', 'equalto', 'time') | map(attribute='at') | list
  == ['00:00:00']
- >-
  homeassistant_commute_groups[0].triggers
  | selectattr('trigger', 'equalto', 'homeassistant') | map(attribute='event') | list
  == ['start']
- >-
  homeassistant_commute_groups[0].triggers
  | selectattr('trigger', 'equalto', 'event') | list
  == [{'trigger': 'event', 'event_type': 'model_y_commute_days_set', 'id': 'set'}]
- "'apa hotel & resort roppongi ekihigashi' in homeassistant_commute_text"
- "'ark hills sengokuyama mori tower' in homeassistant_commute_text"
- "'tns azabudai 3-chome' in homeassistant_commute_text"
- "'| lower' in homeassistant_commute_text"
- "'last_changed' in homeassistant_commute_text"
- "'timedelta(days=29)' in homeassistant_commute_text"
- "'trigger.event.data.dates' in homeassistant_commute_text"
- "'this.attributes.dates' in homeassistant_commute_text"
- homeassistant_commute_sensor.name == 'Model Y Commute Days'
- "'dates' in homeassistant_commute_sensor.attributes"
- homeassistant_commute_80 | length == 1
- homeassistant_commute_90 | length == 1
- "'sensor.model_y_commute_days' in homeassistant_commute_80[0].availability"
- "'sensor.model_y_commute_days' in homeassistant_commute_90[0].availability"
- "'15 * 0.8' in homeassistant_commute_80[0].state"
- "'15 * 0.9' in homeassistant_commute_90[0].state"
- homeassistant_alarm_automations | length == 1
- >-
  homeassistant_alarm_automations[0].triggers
  == [{'trigger': 'state', 'entity_id': ['binary_sensor.model_y_commute_days_80_percent', 'binary_sensor.model_y_commute_days_90_percent'], 'from': 'off', 'to': 'on'}]
- homeassistant_alarm_automations[0].actions[0].action == 'notify.tats_devices'
- homeassistant_alarm_automations[0].actions[0].data.title == '⚠️ ALARM'
- "'sensor.model_y_commute_days' in homeassistant_alarm_automations[0].actions[0].data.message"
- homeassistant_alarm_automations[0].trace.stored_traces == 100
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_commute_days.yml`
Expected: FAIL（`homeassistant_commute_groups | length == 1` が偽）

- [ ] **Step 3: trigger 型ブロックを実装する**

`templates.yaml` の末尾に、Global Constraints のトリガーと名前でブロックを追加する。`variables` で次を順に定義し、sensor の `state` は `{{ dates | count }}`、`attributes.dates` は `{{ dates }}` にする。

- `commute_parkings`: 通勤先の3つの名前（小文字、アルファベット順）
- `today`: `now().date() | string`
- `cutoff`: `(now().date() - timedelta(days=29)) | string`
- `arrived`: ジオフェンスの状態を `| lower` して `commute_parkings` に含まれ、かつ `last_changed` の日付が今日
- `previous`: `trigger.id == 'set'` なら `trigger.event.data.dates | default([])`、それ以外は `this.attributes.dates | default([])`
- `dates`: `(previous + ([today] if arrived else [])) | unique | select('>=', cutoff) | sort | list`

ブロックの直前に、30日のローリングで通勤日数を数える目的と、`last_changed` 条件の理由（0:00 の再計算で前日から停めたままの車を翌日に数えないため）をコメントで書く。binary_sensor は Global Constraints の式で、name は `"Model Y Commute Days 80 Percent"` と `"Model Y Commute Days 90 Percent"`、アイコンは実装者が決める。sensor の `unit_of_measurement` は `"days"`、`state_class: measurement`。

- [ ] **Step 4: アラームを実装する**

alias `"ALARM: Model Y Commute Days Warning"`。トリガーの前に既存と同じ「off から始めることで再起動時に通知を繰り返さない」コメントを付ける。メッセージは `states('sensor.model_y_commute_days')` の日数と、`trigger.entity_id` が 90% 側なら 14、それ以外は 12 のしきい値を入れ、「直近30日の通勤日数」とわかる英文にする。

- [ ] **Step 5: テストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_commute_days.yml roles/homeassistant/tests/model_y_insurance_distance.yml roles/homeassistant/tests/tesla_automation.yml`
Expected: `failed=0`

- [ ] **Step 6: リントとテスト一式を通してコミットする**

Run: `git add roles/homeassistant/tests/model_y_commute_days.yml` の後、`uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも成功

```bash
git add roles/homeassistant/files/templates.yaml roles/homeassistant/files/automations-alarm.yaml roles/homeassistant/tests/model_y_commute_days.yml docs/superpowers/specs/2026-11-13-model-y-commute-days-design.md docs/superpowers/plans/2026-11-13-model-y-commute-days.md
git commit -m "feat(homeassistant): warn when Model Y commute days near the insurance limit"
```

### Task 2: 配備と初期値

**Files:** なし

**Interfaces:**
- Consumes: Task 1 の全エンティティとイベント

- [ ] **Step 1: 差分を確認する**

Run: `ansible-playbook home-primary.yml --tags homeassistant_configuration,homeassistant_automation --check --diff`
Expected: 終了コード 0。差分が `templates.yaml` と `automations-alarm.yaml` だけ

- [ ] **Step 2: 配備する**

Run: Step 1 から `--check` を外して実行し、Home Assistant の再起動を待ってから ha-mcp の `ha_call_service` で `automation.reload` を呼ぶ
Expected: 終了コード 0。`sensor.model_y_commute_days` が `0`（起動トリガーで評価済み）、2つの binary_sensor が `off`、`automation.alarm_model_y_commute_days_warning` が存在する

- [ ] **Step 3: テンプレートの挙動を実機で確かめる**

`ha_eval_template` で、Task 1 の `variables` と同じ式に `previous`、ジオフェンスの状態、`last_changed` の日付を差し替えた次の3つを評価する。
Expected:
- 今日の日付が `previous` にあり、到着済み: 件数が増えない
- 通勤先にいて `last_changed` が昨日: 今日が足されない
- `previous` に30日前の日付がある: その日付が捨てられる

- [ ] **Step 4: 初期値を流し込む**

`ha_get_history` で今日から29日前以降の `sensor.model_y_geofence` を取り、状態を小文字にして通勤先の3つのどれかになった記録の `last_changed` を JST の日付にし、重複を除いて並べる。利用者にその日付と件数を見せ、件数が12以上なら通知が届くことも伝えてから、`ha_call_event` で `event_type: model_y_commute_days_set`、`data: {dates: [...]}` を送る。
Expected: `sensor.model_y_commute_days` の状態が日付の件数と同じで、属性 `dates` が集めた日付と一致する。binary_sensor の状態が件数としきい値の比較と合う

- [ ] **Step 5: 再起動で属性が残ることを確かめる**

Step 4 の `dates` を控え、`ha_restart` で Home Assistant を再起動する。
Expected: 再起動後も `sensor.model_y_commute_days` の `dates` が控えたものと同じ（0:00 をまたいだ場合は古い1日が落ちるだけ）

### Task 3: ダッシュボードと push

**Files:** なし（`dashboard-tesla` は storage モード）

**Interfaces:**
- Consumes: Task 1 の sensor と2つの binary_sensor

- [ ] **Step 1: タイルを追加する**

`MCPORTER_KEEPALIVE=home-assistant` を付けて `ha_config_get_dashboard url_path=dashboard-tesla` で設定と `config_hash` を得る。`model-y` ビューの最初のセクションで、`entity: binary_sensor.model_y_insurance_distance_warning` のタイルの直後に次の3枚を挿入し、`ha_config_set_dashboard` で保存する。他のカードは変えない。各タイルは既存タイルと同じく `features_position: bottom`、`vertical: false`、`state_content: [state, last_changed]` を持つ。

- `sensor.model_y_commute_days`、name `"Commute Days"`、`grid_options: {columns: 12, rows: 1}`
- `binary_sensor.model_y_commute_days_80_percent`、name `"Commute Days 80%"`、`grid_options: {columns: 12, rows: 1}`、`visibility: [{condition: state, entity: binary_sensor.model_y_commute_days_80_percent, state: "on"}]`
- `binary_sensor.model_y_commute_days_90_percent`、name `"Commute Days 90%"`、`grid_options: {columns: 12, rows: 1}`、`visibility: [{condition: state, entity: binary_sensor.model_y_commute_days_90_percent, state: "on"}]`

- [ ] **Step 2: 確認する**

Run: `ha_config_get_dashboard url_path=dashboard-tesla` の出力を `rg -c "model_y_commute_days"` で数える
Expected: 5件（警告タイルは `entity` と `visibility` で2件ずつ）。さらに利用者の Chrome（agent-browser、CDP）で `https://hass.rewse.jp/dashboard-tesla/model-y` を開き、"Insurance Distance Warning" の位置の後ろに "Commute Days" が出ていて、警告タイルの表示が binary_sensor の状態と合うことを確認する

- [ ] **Step 3: 仕様と計画をアーカイブして push する**

`git mv` で spec と plan を `docs/superpowers/archive/specs/`、`docs/superpowers/archive/plans/` に移し、plan 内の Spec のパスを直してコミットする。

```bash
git commit -m "docs: archive Model Y commute days spec and plan"
git -P push
```

Expected: push 成功
