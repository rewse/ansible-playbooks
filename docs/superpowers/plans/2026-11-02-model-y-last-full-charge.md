# Model Y 最終フルチャージ日時 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 最後に `sensor.model_y_battery` が 100 になった日時を `input_datetime` に記録し、フルチャージ催促をその日時から 30 日経過で判定する。

**Architecture:** `input_datetime.model_y_battery_last_full_charge` をオートメーションが更新し、テンプレートの binary_sensor がそれを読む。初期値を入れてから判定を切り替えるため、デプロイを 2 段に分ける(Task 1 で入れ物と記録、Task 2 で判定の切り替え)。ダッシュボードは storage モードなので ha-mcp で書き換える。

**Tech Stack:** Home Assistant YAML、Ansible(`home-primary.yml`)、ha-mcp(mcporter 経由)、TeslaMate(初期値の調査)

**Spec:** `docs/superpowers/specs/2026-11-02-model-y-last-full-charge-design.md`

## Global Constraints

- エンティティ: `input_datetime.model_y_battery_last_full_charge`(`has_date: true`、`has_time: true`)
- オートメーション: id `automation.record_model_y_last_full_charge`、alias `Record Model Y Last Full Charge`、`automations-tesla.yaml` に置く
- トリガー: `numeric_state`、`entity_id: sensor.model_y_battery`、`above: 99`
- binary_sensor の unique_id `binary_sensor.model_y_battery_full_charge_due` は変えない。30 日以上経過で on
- アラーム `automation.alarm_model_y_battery_full_charge_due` は変えない(`from: "off"` を維持)
- ダッシュボードのタイル名は "Last Full Charge"、`state_content: state`。"Full Charge Due" のタイルは変えない
- 作業前に `git -P fetch && git -P log --oneline HEAD..origin/main` で遅れがないか確認し、あれば fast-forward する
- `automations-*.yaml` の配備後は `automation.reload` が必要。`input_datetimes.yaml` は `input_datetime.reload` で反映される。`templates.yaml` と `sensors.yaml` の変更は配備時に Home Assistant が再起動する

## Review Focus

- 初期値なしで判定が切り替わる: `input_datetime` が 1970-01-01 のまま binary_sensor が on になり、誤通知が飛ぶ。Task 2 Step 6 の前に、Task 1 Step 7 で初期値が入っていることを確認する
- 100 のまま Home Assistant が再起動する: `numeric_state` は再起動直後には発火しないので、日時は上書きされない。仕様どおりなのでテストは不要
- `sensor.model_y_battery` が `unavailable` から 100 に戻る: 閾値を超えた値への変化として発火し、日時が更新される。実際に 100% なので許容する
- 統計センサー削除後のレジストリの残骸: `sensor.model_y_battery_max_30_days` が「提供されていない」状態で残る。Task 2 Step 7 で削除する
- 他のダッシュボードからの参照: 全ダッシュボードを調べた結果、参照は `dashboard-tesla` の 1 か所だけ

---

### Task 1: 最終フルチャージ日時の記録

**Files:**
- Modify: `roles/homeassistant/files/input_datetimes.yaml`(`# Vacuum` の前に `# Model Y` 節を追加し、節をアルファベット順に保つ)
- Modify: `roles/homeassistant/files/automations-tesla.yaml`(`Enable Tesla Sentry at TNS Azabudai 3-chome` と `Refresh Tesla Fleet Data` の間に、空行で区切って追加)
- Test: `roles/homeassistant/tests/tesla_automation.yml`、`roles/homeassistant/tests/model_y_full_charge_due.yml`

**Interfaces:**
- Produces: `input_datetime.model_y_battery_last_full_charge`(属性 `timestamp` はエポック秒)

- [ ] **Step 1: テストを書く**

`tesla_automation.yml` の件数を `4` にし、alias のリストを `['Disable Tesla Sentry', 'Enable Tesla Sentry at TNS Azabudai 3-chome', 'Record Model Y Last Full Charge', 'Refresh Tesla Fleet Data']` にする。

`model_y_full_charge_due.yml` に `../files/input_datetimes.yaml` と `../files/automations-tesla.yaml` の読み込みを足し、次を assert するタスクを追加する。既存の assert は Task 2 で書き換えるので残す。`homeassistant_record_automations` は id `automation.record_model_y_last_full_charge` で絞り込む。

```yaml
- homeassistant_input_datetimes.model_y_battery_last_full_charge.has_date
- homeassistant_input_datetimes.model_y_battery_last_full_charge.has_time
- homeassistant_record_automations | length == 1
- >-
  homeassistant_record_automations[0].triggers
  == [{'trigger': 'numeric_state', 'entity_id': 'sensor.model_y_battery', 'above': 99}]
- homeassistant_record_automations[0].actions | length == 1
- homeassistant_record_automations[0].actions[0].action == 'input_datetime.set_datetime'
- >-
  homeassistant_record_automations[0].actions[0].target
  == {'entity_id': 'input_datetime.model_y_battery_last_full_charge'}
- homeassistant_record_automations[0].mode == 'single'
- homeassistant_record_automations[0].trace.stored_traces == 100
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/tesla_automation.yml roles/homeassistant/tests/model_y_full_charge_due.yml`
Expected: 件数と新しい assert で FAIL

- [ ] **Step 3: 実装する**

`input_datetimes.yaml` に `model_y_battery_last_full_charge`(name `"Model Y Battery Last Full Charge"`、icon `"mdi:battery-charging-100"`)を追加する。オートメーションのアクションには `data: timestamp: "{{ now().timestamp() }}"` を渡す。オートメーションの直前に、LFP バッテリーの残量推定を較正するフルチャージ催促のために日時を記録する、という趣旨のコメントを付ける。

- [ ] **Step 4: テストが通ることを確認する**

Run: Step 2 と同じ
Expected: `failed=0`

- [ ] **Step 5: リントとテスト一式を通してコミットする**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも成功

```bash
git add roles/homeassistant/files/input_datetimes.yaml roles/homeassistant/files/automations-tesla.yaml roles/homeassistant/tests/tesla_automation.yml roles/homeassistant/tests/model_y_full_charge_due.yml
git commit -m "feat(homeassistant): record when the Model Y last reached 100%"
```

- [ ] **Step 6: 配備して反映する**

Run: `ansible-playbook home-primary.yml --tags homeassistant_configuration,homeassistant_automation --check --diff` で、差分が上記 2 ファイルだけであることを確認する。確認できたら `--check` なしで実行し、続けて `input_datetime.reload` と `automation.reload` を ha-mcp の `ha_call_service` で呼ぶ。
Expected: 終了コード 0。`input_datetime.model_y_battery_last_full_charge` と `automation.record_model_y_last_full_charge` が存在する

- [ ] **Step 7: TeslaMate から初期値を入れる**

`teslamate` スキルを読み、TeslaMate の記録から `battery_level` が最後に 100 になった時点を探す。直近の 100% 到達のうち、最初に 100 になった時刻を使う。その日時を利用者に見せてから、`input_datetime.set_datetime` で書き込む。
Expected: `state_attr('input_datetime.model_y_battery_last_full_charge', 'timestamp')` が TeslaMate の日時と一致する

### Task 2: 判定の切り替えと統計センサーの削除

**Files:**
- Modify: `roles/homeassistant/files/templates.yaml:281-287`
- Modify: `roles/homeassistant/files/sensors.yaml:117-128`(`# Model Y` 節ごと削除)
- Test: `roles/homeassistant/tests/model_y_full_charge_due.yml`

**Interfaces:**
- Consumes: Task 1 の `input_datetime.model_y_battery_last_full_charge`

- [ ] **Step 1: テストを書き換える**

`homeassistant_max_sensors` 関連の assert を `homeassistant_max_sensors | length == 0` だけにする。binary_sensor の assert は次にする。

```yaml
- homeassistant_due_sensors | length == 1
- "'input_datetime.model_y_battery_last_full_charge' in homeassistant_due_sensors[0].availability"
- "'input_datetime.model_y_battery_last_full_charge' in homeassistant_due_sensors[0].state"
- "'30 * 86400' in homeassistant_due_sensors[0].state"
- "'max_30_days' not in homeassistant_due_sensors[0].state"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_full_charge_due.yml`
Expected: FAIL

- [ ] **Step 3: 実装する**

`availability` は `is_number(state_attr('input_datetime.model_y_battery_last_full_charge', 'timestamp'))` にする。`state` は `now().timestamp() - <その timestamp> >= 30 * 86400` にする。コメントは「最後に 100% になってから 30 日経つと on になる」という内容に直す。`sensors.yaml` からは、統計センサーとその説明コメント、`# Model Y` 見出しを削除する。

- [ ] **Step 4: テストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/model_y_full_charge_due.yml roles/homeassistant/tests/tesla_automation.yml`
Expected: `failed=0`

- [ ] **Step 5: リントとテスト一式を通してコミットする**

Run: Task 1 Step 5 と同じ

```bash
git add roles/homeassistant/files/templates.yaml roles/homeassistant/files/sensors.yaml roles/homeassistant/tests/model_y_full_charge_due.yml
git commit -m "feat(homeassistant): base the Model Y full charge reminder on the last full charge"
```

- [ ] **Step 6: 配備する**

Task 1 Step 7 で初期値が入っていることを確認してから、`ansible-playbook home-primary.yml --tags homeassistant_configuration --check --diff`、続いて `--check` なしで実行する。この配備で Home Assistant が再起動する。
Expected: 終了コード 0。再起動後、binary_sensor が初期値から計算した状態になり、30 日未満なら `off` になる

- [ ] **Step 7: レジストリから統計センサーを削除する**

ha-mcp で `sensor.model_y_battery_max_30_days` のレジストリエントリを削除する。
Expected: `ha_search` で `model_y_battery_max_30_days` が見つからない

### Task 3: ダッシュボードの書き換え

**Files:** なし(`dashboard-tesla` は storage モード)

**Interfaces:**
- Consumes: Task 1 の `input_datetime.model_y_battery_last_full_charge`

- [ ] **Step 1: 書き換える**

`MCPORTER_KEEPALIVE=home-assistant` を付けて BPS キーを取得し、`ha_config_get_dashboard url_path=dashboard-tesla` で `config_hash` を得る。`entity` が `sensor.model_y_battery_max_30_days` のタイルについて、`entity` を `input_datetime.model_y_battery_last_full_charge` に、`name` を `"Last Full Charge"` に、`state_content` を `"state"` に変える。それ以外のキー(`grid_options`、`features_position`、`vertical`)は元のまま、`ha_config_set_dashboard` で保存する。

- [ ] **Step 2: 確認する**

Run: `ha_config_get_dashboard url_path=dashboard-tesla` の出力を `rg "max_30_days|last_full_charge"` で絞り込む
Expected: `max_30_days` は 0 件、`last_full_charge` は 1 件。さらに利用者の Chrome(agent-browser、CDP)で `https://hass.rewse.jp/dashboard-tesla/model-y` を開き、タイルに日時が出ていることを確認する

- [ ] **Step 3: push する**

Run: `git -P push`
Expected: 成功
