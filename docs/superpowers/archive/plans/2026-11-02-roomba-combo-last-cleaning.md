# Roomba Combo 最終掃除日時 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `input_datetime.roomba_combo_next` を `input_datetime.roomba_combo_last_cleaning` に置き換え、自動スタートを最後の掃除から 2 日経過で判定する。

**Architecture:** 記録用オートメーションが `cleaning` 開始時刻を `input_datetime` に書き、自動スタートの条件がそれを読む。どちらも再起動なしで反映できるので配備は 1 回。ダッシュボードは storage モードなので ha-mcp で書き換える。

**Tech Stack:** Home Assistant YAML、Ansible(`home-primary.yml`)、ha-mcp(mcporter 経由)

**Spec:** `docs/superpowers/archive/specs/2026-11-02-roomba-combo-last-cleaning-design.md`

## Global Constraints

- エンティティ: `input_datetime.roomba_combo_last_cleaning`(name `"Roomba Combo Last Cleaning"`、`has_date: true`、`has_time: true`、icon は既存の `mdi:robot-vacuum-alert` を引き継ぐ)
- オートメーション: id `automation.record_roomba_combo_last_cleaning`、alias `Record Roomba Combo Last Cleaning`。トリガーは既存のまま(`vacuum.roomba_combo` が `cleaning` で 30 分)
- 記録値: `trigger.to_state.last_changed` のタイムスタンプ
- 自動スタート条件: `now().timestamp() - state_attr('input_datetime.roomba_combo_last_cleaning', 'timestamp') >= 2 * 86400`
- 初期値: 2026-11-01 17:00:09 JST(Home Assistant の履歴で `cleaning` になった時刻)
- 作業前に `git -P fetch && git -P log --oneline HEAD..origin/main` で遅れがないか確認する

## Review Focus

- 初期値を入れる前: 新しい `input_datetime` は今日の 0 時なので 2 日未満となり、自動スタートしない(安全側)
- 掃除が一時停止して再開した場合: `last_changed` は再開時刻になり、記録が少し遅くなる。自動スタートが遅れる方向なので許容する
- 旧エンティティの残骸: `automation.update_roomba_combo_next_date` がレジストリに残る。Task 2 で削除する
- `roomba_combo_next` の参照漏れ: リポジトリ内と全ダッシュボードで 0 件になることを確認する

---

### Task 1: 最終掃除日時の記録と自動スタート条件

**Files:**
- Modify: `roles/homeassistant/files/input_datetimes.yaml`(`# Vacuum` 節)
- Modify: `roles/homeassistant/files/automations-others.yaml:1-16, 36`
- Create: `roles/homeassistant/tests/roomba_combo.yml`

**Interfaces:**
- Produces: `input_datetime.roomba_combo_last_cleaning`、`automation.record_roomba_combo_last_cleaning`

- [ ] **Step 1: テストを書く**

`model_y_full_charge_due.yml` と同じ形で、`input_datetimes.yaml` と `automations-others.yaml` を読み込んで次を assert する。

```yaml
- "'roomba_combo_next' not in homeassistant_input_datetimes"
- homeassistant_input_datetimes.roomba_combo_last_cleaning.has_date
- homeassistant_input_datetimes.roomba_combo_last_cleaning.has_time
- "'roomba_combo_next' not in (homeassistant_other_automations | to_json)"
- homeassistant_record_automations | length == 1
- >-
  homeassistant_record_automations[0].triggers
  == [{'trigger': 'state', 'entity_id': 'vacuum.roomba_combo', 'to': 'cleaning', 'for': {'minutes': 30}}]
- homeassistant_record_automations[0].actions[0].action == 'input_datetime.set_datetime'
- >-
  homeassistant_record_automations[0].actions[0].target
  == {'entity_id': 'input_datetime.roomba_combo_last_cleaning'}
- "'trigger.to_state.last_changed' in homeassistant_record_automations[0].actions[0].data.timestamp"
- "'input_datetime.roomba_combo_last_cleaning' in (homeassistant_start_automations[0].conditions | to_json)"
- "'2 * 86400' in (homeassistant_start_automations[0].conditions | to_json)"
```

`homeassistant_record_automations` は id `automation.record_roomba_combo_last_cleaning`、`homeassistant_start_automations` は id `automation.start_roomba_combo` で絞り込む。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `ansible-playbook roles/homeassistant/tests/roomba_combo.yml`
Expected: FAIL

- [ ] **Step 3: 実装する**

Global Constraints の値で `input_datetimes.yaml` と `automations-others.yaml` を書き換える。記録用オートメーションには `mode: single` と `trace.stored_traces: 100` を付け、30 分未満の掃除は数えないことと、開始時刻を記録することをコメントで残す。

- [ ] **Step 4: テストが通ることを確認する**

Run: `ansible-playbook roles/homeassistant/tests/roomba_combo.yml`
Expected: `failed=0`

- [ ] **Step 5: リントとテスト一式を通してコミットする**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも成功

```bash
git add roles/homeassistant/files/input_datetimes.yaml roles/homeassistant/files/automations-others.yaml roles/homeassistant/tests/roomba_combo.yml
git commit -m "feat(homeassistant): record when the Roomba Combo last cleaned"
```

### Task 2: 配備と初期値、旧エンティティの削除

**Files:** なし

**Interfaces:**
- Consumes: Task 1 の 2 エンティティ

- [ ] **Step 1: 配備する**

Run: `direnv exec . ansible-playbook home-primary.yml --tags homeassistant_configuration,homeassistant_automation --check --diff` で差分が 2 ファイルだけと確認してから、`--check` なしで実行する。続けて `input_datetime.reload`、`automation.reload` の順に呼ぶ。
Expected: 終了コード 0、新しい 2 エンティティが存在し、`input_datetime.roomba_combo_next` が存在しない

- [ ] **Step 2: 初期値を入れる**

`input_datetime.set_datetime` で `2026-11-01 17:00:09` を書き込む。
Expected: `states('input_datetime.roomba_combo_last_cleaning') == '2026-11-01 17:00:09'`

- [ ] **Step 3: 旧オートメーションをレジストリから削除する**

`ha_remove_entity` で `automation.update_roomba_combo_next_date` を削除する。`input_datetime.roomba_combo_next` がレジストリに残っていれば、それも削除する。
Expected: `ha_search` でどちらも見つからない

### Task 3: ダッシュボードの書き換え

**Files:** なし(storage モード)

- [ ] **Step 1: 書き換える**

BPS キーと `config_hash` を取得し、jq で次の置き換えをした config を `ha_config_set_dashboard` で保存する。ほかのキーは変えない。

- `lovelace`: `entity == "input_datetime.roomba_combo_next"` のタイル → `input_datetime.roomba_combo_last_cleaning`
- `dashboard-internal`: `entity == "automation.update_roomba_combo_next_date"` のタイル → `entity` を `automation.record_roomba_combo_last_cleaning`、`name` を `"Record Last"`、`double_tap_action.url_path` を `https://hass.rewse.jp/config/automation/trace/automation.record_roomba_combo_last_cleaning` に
- `dashboard-internal`: `entity == "input_datetime.roomba_combo_next"` のタイル → `input_datetime.roomba_combo_last_cleaning`

- [ ] **Step 2: 確認して push する**

Run: 全ダッシュボードの config を `rg -c "roomba_combo_next"` で確認してから `git -P push`
Expected: 全ダッシュボードで 0 件、push 成功
