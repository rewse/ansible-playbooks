# Home Assistant のデバイス名とエンティティ ID の統一 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 対象のエリア名、デバイス名、エンティティ名、エンティティ ID を命名ルールにそろえ、リポジトリとリポジトリ外の参照を同じ日に切り替える。

**Architecture:** 一度だけ使う移行ツール `tools/homeassistant_rename/` を作る。ツールは Home Assistant の WebSocket API から登録情報を取り出し、ルールに沿って「旧 → 新」のマッピング CSV を作る。利用者が CSV を確かめたあと、同じ CSV で登録情報、リポジトリ、ダッシュボード、エネルギー設定を書き換える。通知文と HomeKit の名前は、マッピングと無関係に先に直してデプロイする。

**Tech Stack:** Python 3（標準ライブラリ、`websockets`、`pyyaml`）、unittest と pytest、Ansible（`home-primary.yml`）、Home Assistant 2026.11.2 の WebSocket API

**Spec:** `docs/superpowers/specs/2026-11-06-homeassistant-naming-design.md`

## Global Constraints

- 命名ルール、範囲、範囲外は spec の「命名ルール」「範囲外」に従う。この計画はルールを繰り返さない
- エリア名のアポストロフィは ASCII の `'` にする（`Dad's Room`、`Mom's Room`）。ID は `dad_s_room`、`mom_s_room` になる
- エンティティ ID の slug は Home Assistant の `slugify` フィルターで作る。ツールの中で slugify を作り直さない
- デバイスに属するエンティティの ID は、登録情報の `new_entity_id` で変えて履歴を引き継ぐ。エンティティの削除と再作成で変えない
- YAML で `unique_id` か `id` を持つエンティティ（オートメーション、`templates.yaml`、`sensors.yaml`、`mqtt.yaml`、`utility_meters.yaml` など）も、登録情報の `new_entity_id` で ID を変え、`unique_id` と `id` の値は書き換えない。CO2 や電力量の長期統計を残すため（計画での判断）
- キーで ID が決まる YAML のヘルパーとスクリプト（`input_numbers.yaml`、`input_selects.yaml`、`input_datetimes.yaml`、`input_booleans.yaml`、`scripts.yaml`）は、キーごと書き換える。適用前に値を控え、適用後に入れ直す
- 一つの部屋は、Home Assistant とリポジトリを同じ日に切り替える
- Home Assistant のトークンは `direnv exec /Volumes/ExternalHD/git/ansible-playbooks op read op://ansible/jdyfywcw5p3xcet3nxlkvlbonm/credential` で読み、環境変数 `HASS_TOKEN` で渡す。URL は `HASS_URL`（`https://hass.rewse.jp`）で渡す。トークンをファイル、ログ、CSV に書かない
- マッピング CSV と適用の記録は `~/.local/state/homeassistant-rename/` に置き、リポジトリに入れない
- `homeassistant_ha_secondary` が切り替え中（hotel の Home Assistant が動いている）なら、移行を始めない

## Review Focus

- `states.sensor.living_room_temperature.last_changed` のように `states.` の後ろに ID が来る書き方も書き換わる。Task 6 のテスト `test_rewrites_states_attribute_access` で押さえる
- `switch.living_room_humidifier` を書き換えても、`switch.living_room_humidifier_plug` と `switch.living_room_humidifier_switch` は変わらない。Task 6 のテスト `test_does_not_touch_longer_ids` で押さえる
- 新しい ID がほかのエンティティの今の ID と同じでも（入れ替えや連鎖）、途中で `_2` が付かずに目的の ID になる。Task 7 のテスト `test_swap_uses_temporary_ids` と `test_chain_is_ordered` で押さえる
- 二つの行が同じ新しい ID を目指すと、Home Assistant が黙って `_2` を付ける。生成の段階で衝突として `review` にする。Task 5 のテスト `test_duplicate_targets_are_flagged` で押さえる
- `'sensor.' ~ room ~ '_temperature'` のように組み立てた ID と、`area_entities('Dad’s Room')` のようにエリア名を書いた文字列は、置換で拾えない。今のリポジトリにはないが、書き換えのあとに残っていないことを確かめる。Task 6 のテスト `test_check_reports_unknown_and_area_literals` で押さえる

---

## ファイル構成

| パス | 役割 |
|---|---|
| `roles/homeassistant/files/automations-alarm.yaml` | 通知文の名前を部品から組み立てる（Task 1） |
| `roles/homeassistant/files/homekit.yaml` | `entity_config` で名前を固定する（Task 2） |
| `tools/homeassistant_rename/__init__.py` | 空 |
| `tools/homeassistant_rename/hass.py` | WebSocket クライアント |
| `tools/homeassistant_rename/snapshot.py` | 登録情報と状態のスナップショット |
| `tools/homeassistant_rename/rules.py` | 名前と ID の規則（純粋関数） |
| `tools/homeassistant_rename/mapping.py` | マッピング行の生成と CSV の読み書き |
| `tools/homeassistant_rename/rewrite.py` | リポジトリとストレージ JSON の書き換え、参照の検査 |
| `tools/homeassistant_rename/registry.py` | 登録情報への適用、記録、取り消し、YAML 由来の古い登録の削除 |
| `tools/homeassistant_rename/values.py` | ヘルパーの値の控えと入れ直し |
| `tools/homeassistant_rename/__main__.py` | CLI |
| `tests/test_homeassistant_alarm.py` | Task 1 のテストを足す |
| `tests/test_homeassistant_entities.py` | Task 2 のテストを足す |
| `tests/test_homeassistant_rename.py` | ツールのテスト |
| `.pre-commit-config.yaml` | basedpyright の `additional_dependencies` に `websockets` と `pyyaml` を足す |

ツールは移行のためだけに使い、Task 12 で消す。テストは `uv run --with pytest --with ansible-core pytest tests` で動くよう、`websockets` は `hass.py` の関数の中で import する。CLI は `uv run --with websockets --with pyyaml python -m tools.homeassistant_rename <subcommand>` で動かす。

---

### Task 1: 通知文の名前を部品から組み立てる

**Files:**
- Modify: `roles/homeassistant/files/automations-alarm.yaml`（`trigger.to_state.attributes.friendly_name` を使う 5 か所）
- Test: `tests/test_homeassistant_alarm.py`

**Interfaces:**
- Produces: 5 か所の `message` で、トリガーしたエンティティの表示名を同じ式で作る

- [ ] **Step 1: 失敗するテストを書く**

`NotificationDisplayNameTest` を足す。`automations-alarm.yaml` の全 `message` を集め、`friendly_name` を含むものがないことを確かめる。さらに、メッセージのテンプレートを jinja2 で描画する。`area_name`、`device_name`、`entity_name` は辞書を引くスタブ関数、`trigger` は `entity_id` を持つ辞書として渡す。

```python
CASES = [
    # (area, device, entity, expected prefix of the message)
    ("Living Room", "Thermometer", "Temperature", "Living Room Thermometer Temperature"),
    ("Living Room", "Humidifier Plug", "", "Living Room Humidifier Plug"),          # main entity
    ("Living Room", "Living Room Thermometer", "Temperature", "Living Room Thermometer Temperature"),  # area still in device name
    ("Living Room", None, "Living Room Thermometer Fault", "Living Room Thermometer Fault"),  # no device, area in name
    ("Living Room", None, "Thermometer Fault", "Living Room Thermometer Fault"),     # no device, area removed
    (None, None, None, "living_room_unknown"),                                      # nothing known: object ID
]
```

`test_message_names_the_entity` は 5 つのメッセージそれぞれについて、各ケースを描画した結果が期待する文字列で始まることを確かめる。最後のケースでは `trigger.entity_id` を `binary_sensor.living_room_unknown` にする。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_alarm.py -q`
Expected: FAIL（`friendly_name` が残っている）

- [ ] **Step 3: 5 か所の式を置き換える**

規則は次のとおり。エリア、デバイス、エンティティの名前のうち空でないものを空白でつなぐ。デバイス名かエンティティ名の先頭がすでにエリア名なら、エリア名を付けない。どれもなければ `trigger.entity_id.split('.')[1]` を使う。5 か所とも同じ式にする。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_alarm.py -q`
Expected: PASS

- [ ] **Step 5: デプロイして確かめる**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags homeassistant_automation --diff`、続けて `mcporter call home-assistant.ha_call_service domain=automation service=reload`
Expected: exit 0。`mcporter call home-assistant.ha_eval_template` で Step 3 の式を `binary_sensor.entrance_door` と `switch.living_room_humidifier_plug` について描画し、それぞれ `Entrance Door Sensor Door` と `Living Room Humidifier Plug` になる。`sudo docker logs homeassistant` に reload のエラーがない

- [ ] **Step 6: コミットする**

```bash
git add roles/homeassistant/files/automations-alarm.yaml tests/test_homeassistant_alarm.py
git commit -m "fix(homeassistant): build alarm notification names from area, device, and entity"
```

### Task 2: HomeKit の名前を固定する

**Files:**
- Modify: `roles/homeassistant/files/homekit.yaml`
- Test: `tests/test_homeassistant_entities.py`

- [ ] **Step 1: 失敗するテストを書く**

`HomeKitNameTest.test_every_included_entity_has_a_unique_name` を足す。`include_entities` のすべてに `entity_config.<entity_id>.name` があり、名前が重複せず、`’` を含まないことを確かめる。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_entities.py -q`
Expected: FAIL

- [ ] **Step 3: `entity_config` を足す**

名前は次のとおりにする。今の表示名をもとに、アポストロフィを `'` にし、`Plug` を外した。

| entity_id | name |
|---|---|
| `alarm_control_panel.entrance` | `Entrance Alarm` |
| `alarm_control_panel.home` | `Home Alarm` |
| `climate.dads_room_ac` | `Dad's Room AC` |
| `climate.living_room_ac` | `Living Room AC` |
| `climate.moms_room_ac` | `Mom's Room AC` |
| `light.living_room_footlight` | `Living Room Footlight` |
| `light.living_room_lights` | `Living Room Lights` |
| `light.living_room_shelf_light` | `Living Room Shelf Light` |
| `sensor.dads_room_co2` | `Dad's Room CO2` |
| `sensor.living_room_co2` | `Living Room CO2` |

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_entities.py -q`
Expected: PASS

- [ ] **Step 5: デプロイして確かめる**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags homeassistant_configuration --diff`
Expected: exit 0。Home Assistant が再起動したあと（5 分ほどかかる）、iPhone のホームアプリで 10 個のアクセサリが表の名前で見える。利用者に確かめてもらう

- [ ] **Step 6: コミットする**

```bash
git add roles/homeassistant/files/homekit.yaml tests/test_homeassistant_entities.py
git commit -m "fix(homeassistant): pin HomeKit accessory names"
```

### Task 3: WebSocket クライアントとスナップショット

**Files:**
- Create: `tools/homeassistant_rename/__init__.py`、`hass.py`、`snapshot.py`、`__main__.py`
- Modify: `.pre-commit-config.yaml`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Produces:
  - `class HassClient` in `hass.py`: `async connect(url: str, token: str) -> HassClient`、`async call(type_: str, **payload) -> Any`（`result` を返し、`success: false` で `HassError` を送出）、`async render(template: str) -> str`（`render_template` の購読で最初の結果を返す）、`async close() -> None`
  - `async slugify_all(client: HassClient, names: list[str]) -> dict[str, str]`（`{{ names | map('slugify') | list | tojson }}` を一度描画する）
  - `@dataclass Snapshot` in `snapshot.py`: `areas: list[dict]`、`devices: list[dict]`、`entities: list[dict]`、`states: dict[str, dict]`。`save(path)` と `load(path) -> Snapshot`
  - `async fetch_snapshot(client) -> Snapshot`（`config/area_registry/list`、`config/device_registry/list`、`config/entity_registry/list`、`get_states`）
  - CLI `snapshot --out <path>`

- [ ] **Step 1: 失敗するテストを書く**

`SnapshotTest.test_round_trip`（`save` と `load` で同じ内容に戻る）と `SnapshotTest.test_states_are_keyed_by_entity_id` を書く。`HassClient` はテストしない（薄いネットワーク層）。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q`
Expected: FAIL（モジュールがない）

- [ ] **Step 3: モジュールを書く**

`.pre-commit-config.yaml` の basedpyright に `websockets` と `pyyaml` を足す。`__main__.py` は `argparse` のサブコマンドで、`HASS_URL` と `HASS_TOKEN` を環境変数から読む。

- [ ] **Step 4: テストと lint を通す**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q` と `git add -A tools tests .pre-commit-config.yaml && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: PASS

- [ ] **Step 5: 実機で読めることを確かめる**

Run: `mkdir -p ~/.local/state/homeassistant-rename && HASS_URL=https://hass.rewse.jp HASS_TOKEN="$(direnv exec /Volumes/ExternalHD/git/ansible-playbooks op read op://ansible/jdyfywcw5p3xcet3nxlkvlbonm/credential)" uv run --with websockets --with pyyaml python -m tools.homeassistant_rename snapshot --out ~/.local/state/homeassistant-rename/snapshot.json`
Expected: exit 0。エリア 8、デバイス 288 前後、状態 1,840 前後が入っている

- [ ] **Step 6: コミットする**

```bash
git add tools/homeassistant_rename tests/test_homeassistant_rename.py .pre-commit-config.yaml
git commit -m "feat(homeassistant): add a registry snapshot tool for the naming migration"
```

### Task 4: 名前と ID の規則

**Files:**
- Create: `tools/homeassistant_rename/rules.py`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Produces（すべて純粋関数）:
  - `normalize_apostrophe(name: str) -> str`
  - `strip_area(name: str, area_names: Iterable[str]) -> str`（`’` と `'` を同じとみなし、先頭のエリア名と続く空白を外す）
  - `normalize_modifiers(name: str) -> tuple[str, bool]`（新しい名前と、要確認かどうか）
  - `expand_abbreviations(object_id: str) -> str`
  - `in_scope(device: dict | None, entity: dict, area_id: str | None) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`RulesTest` に次の表を `subTest` で書く。

```python
STRIP_AREA = [
    ("Living Room Thermometer", "Thermometer"),
    ("Dad’s Room AC", "AC"),
    ("Dad's Room AC", "AC"),
    ("Living Room", ""),            # Hue room group: needs a new name
    ("Thermometer", "Thermometer"),
]
MODIFIERS = [
    ("Window Sensor N", ("Window Sensor North", False)),
    ("Presence Sensor E", ("Presence Sensor East", False)),
    ("Left Light", ("Light Left", False)),
    ("Center Plug", ("Plug Center", False)),
    ("Study Floor Heater", ("Floor Heater North", False)),
    ("Study Downlights", ("Downlights North", False)),
    ("Floor Heater 2", ("Floor Heater 2", True)),       # numbered: review
    ("Plug East", ("Plug East", False)),
]
ABBREVIATIONS = [
    ("living_room_temp_max_diff_present_summer_midnight",
     "living_room_temperature_maximum_difference_present_summer_midnight"),
    ("dads_room_humidity_min_diff", "dads_room_humidity_minimum_difference"),
    ("living_room_ac_temperature", "living_room_ac_temperature"),
    ("living_room_tv_plug", "living_room_tv_plug"),
    ("moms_room_air_purifier_pm2_5", "moms_room_air_purifier_pm2_5"),
    ("template_x", "template_x"),   # "temp" only as a whole token
]
```

`in_scope` は、エリアのないデバイス、エリアのない `person` と `device_tracker`、インテグレーションが `unifi` と `unifiprotect` のデバイス、`backup`、`sun`、`hassio` の各エンティティで `False`、エリアを持つデバイスのエンティティとエリアを持つ自作エンティティで `True` になることを確かめる。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Rules`
Expected: FAIL

- [ ] **Step 3: `rules.py` を書く**

略語の対応は `temp → temperature`、`diff → difference`、`max → maximum`、`min → minimum` の 4 つで、`_` で区切ったトークン単位で置き換える。方角の対応は `N/E/S/W/NE/NW/SE/SW` から一語の方角へ。前置きの修飾語は `Left`、`Right`、`Middle`、`Center`、`Top`、`Bottom`、`Entrance` で、末尾に移す。`Study` は `North` として末尾に付ける。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Rules`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tools/homeassistant_rename/rules.py tests/test_homeassistant_rename.py
git commit -m "feat(homeassistant): encode the naming rules for the migration"
```

### Task 5: マッピングの生成

**Files:**
- Create: `tools/homeassistant_rename/mapping.py`
- Modify: `tools/homeassistant_rename/__main__.py`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Consumes: `Snapshot`、`rules.*`、`slugify_all`
- Produces:
  - `@dataclass Row`: `room: str`、`kind: Literal["area", "device", "entity"]`、`source: Literal["registry", "yaml_key", "yaml_unique_id"]`、`integration: str`、`key: str`（エリア ID、デバイス ID、エンティティの今の ID）、`old_name: str`、`new_name: str`、`old_id: str`、`new_id: str`、`status: Literal["auto", "review", "skip"]`、`note: str`
  - `build_rows(snapshot: Snapshot, yaml_sources: YamlSources, slugify: Callable[[list[str]], dict[str, str]]) -> list[Row]`
  - `@dataclass YamlSources`: `key_ids: set[str]`（キーで決まる ID）、`unique_ids: set[str]`。`load_yaml_sources(files_dir: Path) -> YamlSources`
  - `write_csv(rows, path)`、`read_csv(path) -> list[Row]`
  - CLI `map --snapshot <path> --out <csv>`

- [ ] **Step 1: 失敗するテストを書く**

小さな `Snapshot` を手で作り、`slugify` にはテスト用の簡易関数を渡す。

- `test_device_entity_id_follows_area_device_entity`: エリア `Living Room`、デバイス `Living Room Thermometer`、エンティティ `sensor.living_room_temperature`（`original_name: Temperature`）から、デバイス行の `new_name` が `Thermometer`、エンティティ行の `new_id` が `sensor.living_room_thermometer_temperature` になる
- `test_main_entity_uses_device_name_only`: `name: ""` のプラグのスイッチは `switch.living_room_humidifier_plug` になる
- `test_area_rows_use_ascii_apostrophe`: `Dad’s Room` のエリア行の `new_name` が `Dad's Room`、その部屋のエンティティの ID が `dad_s_room_` で始まる
- `test_thermometer_pairs_get_primary_and_secondary`: Dad's Room の `Thermometer` と `SwitchBot Meter` が `Thermometer Primary` と `Thermometer Secondary` になる。Balcony の `SwitchBot Outdoor Meter` と `SwitchBot Meter` も同じ
- `test_yaml_key_helpers_are_marked`: `input_number.living_room_temp_target` が `source == "yaml_key"` になり、`new_id` で略語が展開される
- `test_yaml_unique_id_entities_keep_unique_id`: `unique_id` を持つ YAML のエンティティは `source == "yaml_unique_id"` になる
- `test_duplicate_targets_are_flagged`: 二つの行が同じ `new_id` になると、両方が `status == "review"` で `note` に `conflict` を含む
- `test_unchanged_rows_are_skipped`: 名前も ID も変わらない行は `status == "skip"`
- `test_csv_round_trip`

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Mapping`
Expected: FAIL

- [ ] **Step 3: `mapping.py` と `map` サブコマンドを書く**

デバイスに属するエンティティの ID は、spec の「2026.11 更新後に確かめたこと」のとおり、新しいエリア名、親デバイス名、新しいデバイス名、エンティティ名（登録名があればそれ、なければ `original_name`、Main entity では省く）を空白でつなぎ、`slugify` した結果を使う。デバイスに属さないエンティティは、今の ID に `strip_area` 相当の置き換え（エリアの slug を新しいエリアの slug に）と `expand_abbreviations` を当てる。温湿度計の組は、エリア名を外した名前が `Thermometer` か `SwitchBot Outdoor Meter` のものを `Thermometer Primary`、`SwitchBot Meter` のものを `Thermometer Secondary` にする。同じ部屋に片方しかなければ `Thermometer` にする。規則で決められないもの（`normalize_modifiers` の要確認、エリア名を外して空になったデバイス、型番らしいデバイス名）は `review` にする。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Mapping`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tools/homeassistant_rename tests/test_homeassistant_rename.py
git commit -m "feat(homeassistant): generate the naming migration mapping"
```

### Task 6: リポジトリとストレージの書き換え、参照の検査

**Files:**
- Create: `tools/homeassistant_rename/rewrite.py`
- Modify: `tools/homeassistant_rename/__main__.py`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Consumes: `Row`、`read_csv`
- Produces:
  - `rewrite_text(text: str, id_map: Mapping[str, str]) -> str`
  - `rewrite_yaml_keys(text: str, key_map: Mapping[str, tuple[str, str]]) -> str`（ヘルパーとスクリプトのトップレベルのキーと、その `name:` を、`旧オブジェクト ID → (新オブジェクト ID, 新しい名前)` で書き換える）
  - `rewrite_yaml_names(text: str, name_map: Mapping[str, str]) -> str`（`unique_id` か `id` が一致するブロックの `name:` か `alias:` を新しい名前にする。`unique_id` と `id` の値は変えない）
  - `rewrite_repo(root: Path, rows: list[Row]) -> list[Path]`（`status == "auto"` の行だけを使い、変えたファイルを返す）
  - `check(root: Path, valid_ids: set[str], old_area_names: set[str]) -> list[str]`（問題の一覧。`valid_ids` はスナップショットの ID をマッピングで移した集合）
  - CLI `rewrite --mapping <csv> [--room <room>]`、`check --snapshot <path> --mapping <csv>`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_rewrites_states_attribute_access(self):
    self.assertEqual(
        rewrite_text("states.sensor.living_room_temperature.last_changed",
                     {"sensor.living_room_temperature": "sensor.living_room_thermometer_temperature"}),
        "states.sensor.living_room_thermometer_temperature.last_changed")

def test_does_not_touch_longer_ids(self):
    text = "switch.living_room_humidifier switch.living_room_humidifier_plug switch.living_room_humidifier_switch"
    out = rewrite_text(text, {"switch.living_room_humidifier": "switch.x"})
    self.assertEqual(out, "switch.x switch.living_room_humidifier_plug switch.living_room_humidifier_switch")
```

ほかに次を書く。

- `test_unique_id_and_id_values_are_kept`: `unique_id: sensor.dads_room_co2` と `- id: automation.alarm_dads_room_co2` の行は変わらず、同じファイルの参照は変わる
- `test_yaml_keys_are_renamed`: `input_numbers.yaml` の `living_room_temp_target:` が新しいキーになり、その `name:` が `new_name` になる
- `test_yaml_names_follow_unique_id`: `templates.yaml` で `unique_id: binary_sensor.dads_room_humidity_disagreement` のブロックの `name:` が新しい名前になり、隣のブロックは変わらない
- `test_check_reports_unknown_and_area_literals`: `valid_ids` にない `sensor.*` の参照、`'sensor.' ~ room` のような組み立て、`Dad’s Room` という文字列を、それぞれ問題として返す

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Rewrite`
Expected: FAIL

- [ ] **Step 3: `rewrite.py` を書く**

ID の前は行頭か `[a-z0-9_.]` 以外か `states.`、後ろは `[a-z0-9_]` 以外のときだけ一致させる。長い ID から順に置き換える。対象は `roles/homeassistant/files/`、`roles/homeassistant/templates/`、`roles/homeassistant/tests/`、`tests/test_homeassistant_*.py`。`roles/homeassistant/tests/` で YAML の `id` を引くための値（`alarm_id` など）は `id` と同じく変えない。どれが引くための値かは、書き換えたあとにテスト用プレイブックが通るかで判断する。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Rewrite`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tools/homeassistant_rename tests/test_homeassistant_rename.py
git commit -m "feat(homeassistant): rewrite entity references from the naming mapping"
```

### Task 7: 登録情報への適用と取り消し

**Files:**
- Create: `tools/homeassistant_rename/registry.py`
- Modify: `tools/homeassistant_rename/__main__.py`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Consumes: `Row`、`HassClient`
- Produces:
  - `@dataclass Op`: `kind: Literal["area", "device", "entity"]`、`key: str`、`payload: dict`、`undo: dict`
  - `plan_ops(rows: list[Row], existing_ids: set[str]) -> list[Op]`（エリア、デバイス、エンティティの順。エンティティは `source != "yaml_key"` の行だけ）
  - `async apply_ops(client, ops, journal: Path, dry_run: bool) -> None`（一つ適用するたびに記録へ追記する）
  - `async revert(client, journal: Path) -> None`（記録を逆順にたどる）
  - `async remove_orphans(client, rows: list[Row]) -> list[str]`（`yaml_key` の古い ID で、状態がなく登録だけ残るものを `config/entity_registry/remove` で消す）
  - `async assign_areas(client, rows: list[Row]) -> None`（`yaml_key` の新しい ID に `room` のエリアを割り当てる。デプロイのあとに呼ぶ）
  - CLI `apply --mapping <csv> [--room <room>] [--dry-run]`、`revert --journal <path>`、`remove-orphans --mapping <csv>`、`assign-areas --mapping <csv>`

呼ぶ API は `config/area_registry/update`（`area_id`、`name`）、`config/device_registry/update`（`device_id`、`name_by_user`）、`config/entity_registry/update`（`entity_id`、`new_entity_id`、必要なら `name`、`area_id`）。デバイスに属さないエンティティには、`room` のエリアを `area_id` で割り当てる。

- [ ] **Step 1: 失敗するテストを書く**

呼び出しを記録する偽のクライアントを使う。

- `test_order_is_area_device_entity`
- `test_swap_uses_temporary_ids`: `a → b` と `b → a` を、`a → a_renaming`、`b → a`、`a_renaming → b` の 3 手にする
- `test_chain_is_ordered`: `a → b`、`b → c` で、`b → c` を先に行う
- `test_dry_run_sends_nothing`
- `test_journal_allows_revert`: 適用のあと `revert` すると、逆の呼び出しが逆順で出る
- `test_yaml_key_rows_are_not_sent_to_registry`

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Registry`
Expected: FAIL

- [ ] **Step 3: `registry.py` を書く**

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k Registry`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tools/homeassistant_rename tests/test_homeassistant_rename.py
git commit -m "feat(homeassistant): apply and revert naming changes in the registry"
```

### Task 8: ヘルパーの値の控えと入れ直し、ストレージの書き換え

**Files:**
- Create: `tools/homeassistant_rename/values.py`
- Modify: `tools/homeassistant_rename/rewrite.py`、`tools/homeassistant_rename/__main__.py`
- Test: `tests/test_homeassistant_rename.py`

**Interfaces:**
- Consumes: `Row`、`HassClient`、`rewrite_text`
- Produces:
  - `capture(snapshot: Snapshot, rows: list[Row]) -> dict[str, dict]`（`yaml_key` 行の今の状態を新しい ID で引けるようにする）
  - `restore_calls(captured: dict[str, dict]) -> list[tuple[str, str, dict]]`（`(domain, service, data)` の一覧）
  - `async rewrite_storage(client, id_map, dry_run: bool) -> list[str]`（`lovelace/dashboards/list` の全ダッシュボードと既定のダッシュボードを `lovelace/config` で読み、`rewrite_text` を JSON 文字列に当てて `lovelace/config/save` する。`energy/get_prefs` と `energy/save_prefs` も同じ）
  - CLI `capture --snapshot <path> --mapping <csv> --out <json>`、`restore --captured <json>`、`rewrite-storage --mapping <csv> [--dry-run]`

- [ ] **Step 1: 失敗するテストを書く**

- `test_restore_calls_per_domain`: `input_number` は `set_value`、`input_select` は `select_option`、`input_datetime` は `set_datetime`（`has_date` と `has_time` に応じて `datetime`、`date`、`time`）、`input_boolean` は `turn_on` か `turn_off`
- `test_unavailable_values_are_not_restored`: `unknown` と `unavailable` は呼び出しを作らない
- `test_storage_rewrite_keeps_unrelated_text`: ダッシュボードの JSON で、対象の ID だけが変わる

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q -k "Values or Storage"`
Expected: FAIL

- [ ] **Step 3: `values.py` と `rewrite_storage` を書く**

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_homeassistant_rename.py -q`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tools/homeassistant_rename tests/test_homeassistant_rename.py
git commit -m "feat(homeassistant): preserve helper values and rewrite dashboards in the migration"
```

### Task 9: マッピングを作って利用者に確かめてもらう

**Files:**
- Modify: `AGENTS.md`（「Repository Operations」の「Home Assistant」に、`~/.local/state/homeassistant-rename/` の消去方針を一行足す。移行が終わってから 30 日後に消す）

- [ ] **Step 1: スナップショットとマッピングを作る**

Run: Task 3 Step 5 の `snapshot`、続けて `... python -m tools.homeassistant_rename map --snapshot ~/.local/state/homeassistant-rename/snapshot.json --out ~/.local/state/homeassistant-rename/mapping.csv`
Expected: exit 0。`review` の行数と `conflict` の行数を数えて報告する

- [ ] **Step 2: 利用者に CSV を確かめてもらう**

`review` の行（修飾語、一般名称、Plug と Switch の役割、Hue のルームグループの新しい名前、`South` 側のデバイス）を利用者に埋めてもらう。すべての行が `auto` か `skip` になるまで繰り返す。`conflict` が残ったまま次に進まない

- [ ] **Step 3: 消去方針を AGENTS.md に足してコミットする**

```bash
git add AGENTS.md
git commit -m "docs: add a purge policy for the Home Assistant rename state"
```

### Task 10: リポジトリの書き換えを用意する

**Files:**
- Modify: `roles/homeassistant/files/*`、`roles/homeassistant/tests/*`、`tests/test_homeassistant_*.py`（ツールが書き換える）

- [ ] **Step 1: 書き換える**

Run: `... python -m tools.homeassistant_rename rewrite --mapping ~/.local/state/homeassistant-rename/mapping.csv`

- [ ] **Step 2: 移行後の ID で参照を検査する**

Run: `... python -m tools.homeassistant_rename check --snapshot ~/.local/state/homeassistant-rename/snapshot.json --mapping ~/.local/state/homeassistant-rename/mapping.csv`
Expected: 問題が 0 件

- [ ] **Step 3: テストと lint を通す**

Run: `uv run --with pytest --with ansible-core pytest tests -q`、`for f in roles/homeassistant/tests/*.yml; do ansible-playbook "$f" || break; done`、`uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて exit 0

- [ ] **Step 4: コミットする（まだデプロイしない）**

```bash
git add roles/homeassistant tests
git commit -m "refactor(homeassistant): rename entity references to the unified naming"
```

### Task 11: 移行する

一日で家全体を切り替える。途中で止めるときは、`revert` で登録情報を戻し、Task 10 のコミットをデプロイしないまま残す。

- [ ] **Step 1: 前提を確かめる**

hotel の Home Assistant が止まっていること（切り替え中でない）と、`mcporter call home-assistant.ha_eval_template` で状態が読めることを確かめる。Home Assistant のバックアップを取る（`mcporter call home-assistant.ha_call_service domain=backup service=create`）

- [ ] **Step 2: 最新のスナップショットを取り、ヘルパーの値を控える**

Run: `snapshot` のあと `capture --snapshot ... --mapping ... --out ~/.local/state/homeassistant-rename/captured.json`
Expected: `yaml_key` 行の数だけ値が入っている

- [ ] **Step 3: 登録情報を変える**

Run: `apply --mapping ... --dry-run` で呼び出しを確かめてから、`apply --mapping ...`
Expected: exit 0。`~/.local/state/homeassistant-rename/journal.jsonl` に全件が記録されている。`_2` で終わる新しい ID がない

- [ ] **Step 4: リポジトリをデプロイする**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags homeassistant_configuration,homeassistant_automation --diff`、続けて `automation.reload`、`input_number.reload`、`input_select.reload`、`input_datetime.reload`、`input_boolean.reload`、`script.reload`
Expected: exit 0。再起動が終わってから次に進む

- [ ] **Step 5: 値を入れ直し、古い登録を消す**

Run: `restore --captured ~/.local/state/homeassistant-rename/captured.json`、`assign-areas --mapping ...`、`remove-orphans --mapping ...`
Expected: 新しい ID のヘルパーが控えた値になり、エリアが付いている

- [ ] **Step 6: ダッシュボードとエネルギー設定を書き換える**

Run: `rewrite-storage --mapping ... --dry-run` のあと `rewrite-storage --mapping ...`

- [ ] **Step 7: リポジトリ外を直す**

Alexa アプリでデバイスを検出し直し、定型アクションが動くことを利用者に確かめてもらう。ホームアプリで部屋の割り当てとオートメーションを利用者に確かめてもらう

- [ ] **Step 8: 動作を確かめる**

`sudo docker logs homeassistant` と Repairs に、存在しないエンティティへの参照がない。新しいスナップショットで `check` が 0 件。`sensor.living_room_thermometer_temperature` の履歴に移行前の値が残っている。故障検知のテンプレート（`binary_sensor.*_thermometer_fault`）が `off` になっている

- [ ] **Step 9: プッシュする**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: exit 0。利用者の了承を得てから `main` に入れる

### Task 12: 後片付け

- [ ] **Step 1: ツールを消す**

`tools/homeassistant_rename/` と `tests/test_homeassistant_rename.py` を消し、`.pre-commit-config.yaml` に足した依存を戻す。

- [ ] **Step 2: テストと lint を通してコミットする**

Run: `uv run --with pytest --with ansible-core pytest tests -q` と pre-commit
Expected: PASS

```bash
git add -A tools tests .pre-commit-config.yaml
git commit -m "chore(homeassistant): remove the one-time naming migration tool"
```

- [ ] **Step 3: spec と計画を archive に移す**

`main` に入れるコミットで、spec と計画を `docs/superpowers/archive/` に移す。
