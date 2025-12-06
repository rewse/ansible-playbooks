---
inclusion: fileMatch
fileMatchPattern: "**/homeassistant/**/*.yaml"
---

# Home Assistant 開発ガイドライン

## YAML スタイルガイド

Home Assistant の公式 YAML スタイルガイド（[developers.home-assistant.io/docs/documenting/yaml-style-guide/](https://developers.home-assistant.io/docs/documenting/yaml-style-guide/)）に基づいたガイドラインです。

### インデント

- インデントには**スペース2つ**を使用する
- タブは使用しない
- ネストされた要素は親要素から2スペースインデントする

```yaml
# 良い例
automation:
  - alias: Good example
    trigger:
      - platform: state
        entity_id: binary_sensor.motion
```

### 真偽値

- 真偽値は `true` と `false` を使用する（小文字）
- `yes`/`no` や `on`/`off` などの省略形は使用しない（YAML 1.2仕様との互換性のため）

```yaml
# 良い例
one: true
two: false

# 悪い例
one: True
two: on
three: yes
```

### コメント

- コメントはインデントレベルに合わせる
- コメントは対象行の上に書くことが望ましい
- コメントは大文字で始め、`#` とコメントの間にスペースを入れる

```yaml
# 良い例
example:
  # コメント
  one: true

# 許容可能だが上記が望ましい
example:
  one: true # コメント
```

### シーケンス（リスト）

- ブロックスタイルのシーケンスを優先する
- フロースタイル（`[1, 2, 3]`）は可能な限り避ける

#### ブロックスタイルシーケンス

```yaml
# 良い例
example:
  - 1
  - 2
  - 3

# 悪い例
example:
- 1
- 2
- 3
```

#### フロースタイルシーケンス

使用する場合は、カンマの後にスペースを入れ、開始・終了括弧の前後にスペースを入れない：

```yaml
# 良い例
example: [1, 2, 3]

# 悪い例
example: [ 1,2,3 ]
example: [ 1, 2, 3 ]
```

### マッピング

- マッピングはブロックスタイルのみを使用する
- フロースタイル（JSON風の記法）は使用しない

```yaml
# 良い例
example:
  one: 1
  two: 2

# 悪い例
example: { one: 1, two: 2 }
```

### Null値

- Null値は暗黙的に表現する
- 明示的なNull値（`~` や `null`）は避ける

```yaml
# 良い例
example:

# 悪い例
example: ~
example: null
```

### 文字列

- 文字列は**ダブルクォート**（`"`）で囲むことが望ましい

```yaml
# 良い例
example: "Hi there!"

# 避けるべき例
example: Hi there!

# 悪い例
example: 'Hi there!'
```

## テンプレート記法

### 関数とフィルターの使用

Home Assistantのテンプレートでは、フィルターよりも関数を優先して使用してください。関数はより明示的で、コードの可読性と保守性が向上します。

#### 推奨される方法（関数を使用）

```yaml
# 整数変換に関数を使用
state: "{{ int(state_attr('sensor.example', 'value')) }}"

# 浮動小数点変換に関数を使用
state: "{{ float(states('sensor.temperature')) }}"

# 文字列置換に関数を使用
state: "{{ state_attr('sensor.example', 'text') | replace('%', '') }}"
```

#### 避けるべき方法（フィルターのみを使用）

```yaml
# 整数変換にフィルターを使用（避ける）
state: "{{ state_attr('sensor.example', 'value') | int }}"

# 浮動小数点変換にフィルターを使用（避ける）
state: "{{ states('sensor.temperature') | float }}"
```

### テンプレート構造

- 100文字を超えるテンプレートには複数行形式（`>-`）を使用する
- 100文字を超えないテンプレートには一行形式（`"{{ ... }}"`）を使用する
- テンプレート内の条件文は適切にインデントする

### センサー定義

- すべてのセンサーに `unique_id` を設定する
- 適切な `device_class` と `state_class` を設定する
- 測定値には適切な `unit_of_measurement` を設定する

## ベストプラクティス

1. **明示的な型変換**: 値を操作する前に、明示的に型変換を行う（例: `int()`, `float()`）
2. **エラーハンドリング**: 値が存在しない場合のデフォルト値を設定する
3. **コメント**: 複雑なテンプレートにはコメントを追加する
4. **命名規則**: センサー名は一貫した命名規則に従う
5. **再利用**: 共通のテンプレートは再利用可能な形で設計する

## 例

### 良い例

```yaml
- template:
  - sensor:
      - unique_id: sensor.outside_temperature
        name: "Outside Temperature"
        state: "{{ float(states('sensor.weather_temperature')) }}"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
```

### 避けるべき例

```yaml
- platform: template
  sensors:
    outside_temperature:
      friendly_name: "Outside Temperature"
      value_template: "{{ states('sensor.weather_temperature') | float(0) }}"
      unit_of_measurement: "°C"
```

## ファイル構成

### コンポーネント別のファイル分割

- 関連するコンポーネントごとにファイルを分割する
- 論理的なグループごとにファイルを整理する
- 大きなファイルは小さな管理しやすいファイルに分割する

```
homeassistant/
  sensors.yaml      # センサー定義
  templates.yaml    # テンプレートセンサー
  automations.yaml  # 自動化
  scripts.yaml      # スクリプト
  scenes.yaml       # シーン
```

これらのファイルは `configuration.yaml` から以下のように読み込まれている。

```
sensor: !include sensors.yaml
shell_command: !include shell_commands.yaml
switch: !include switches.yaml
template: !include templates.yaml
```

そのため、分割されたファイルは先頭のkeyを省略する必要がある。

#### 良い例

```
- platform: statistics
  unique_id: sensor.balcony_humidity_difference_average
  name: "Balcony Humidity Difference Average"
  entity_id: sensor.balcony_humidity_difference
  state_characteristic: mean
  max_age:
    hours: 51
- platform: statistics
  unique_id: sensor.balcony_temp_average
  name: "Balcony Temperature Average"
  entity_id: sensor.balcony_temperature
  state_characteristic: mean
  max_age:
    hours: 24
```

#### 悪い例

```
sensor:
  - platform: statistics
    unique_id: sensor.balcony_humidity_difference_average
    name: "Balcony Humidity Difference Average"
    entity_id: sensor.balcony_humidity_difference
    state_characteristic: mean
    max_age:
      hours: 51
  - platform: statistics
    unique_id: sensor.balcony_temp_average
    name: "Balcony Temperature Average"
    entity_id: sensor.balcony_temperature
    state_characteristic: mean
    max_age:
      hours: 24
```

### コメント

- セクションの開始時にはコメントを使用して内容を説明する
- 複雑な設定には説明コメントを追加する
- コメントは `#` の後にスペースを入れる

```yaml
# Balcony sensors
- platform: template
  sensors:
    balcony_temperature:
      friendly_name: "Balcony Temperature"
      # Average of two temperature sensors for better accuracy
      value_template: >-
        {{ (float(states('sensor.balcony_temp_1')) + 
            float(states('sensor.balcony_temp_2'))) / 2 }}
```

### 命名規則

- エンティティIDはスネークケース（小文字とアンダースコア）を使用する
- 関連するエンティティには一貫したプレフィックスを使用する
- 名前は具体的で説明的にする

```yaml
# 良い例
sensor:
  - platform: template
    sensors:
      living_room_temperature:
        friendly_name: "Living Room Temperature"
      living_room_humidity:
        friendly_name: "Living Room Humidity"
```

## 設定のベストプラクティス

### 再利用可能な設定

- 共通の設定は再利用可能な形で設計する
- パッケージ機能を活用して関連する設定をグループ化する

### バージョン管理

- 設定ファイルはバージョン管理システム（Git など）で管理する
- 変更履歴を追跡し、問題が発生した場合に以前の状態に戻せるようにする

### テスト

- 設定変更後は Home Assistant の設定チェック機能を使用して検証する
- 大きな変更を行う前にバックアップを作成する

### セキュリティ

- 機密情報（パスワード、トークン、APIキーなど）は `!secret` を使用して保護する
- 公開リポジトリに機密情報を含めない

```yaml
# 良い例
http:
  api_password: !secret http_password
```
#### 複数行文字列

`\n` などの改行指示子の使用や、長い一行の文字列は避けてください。代わりに、リテラルスタイル（改行を保持）とフォールドスタイル（改行を保持しない）の複数行文字列を使用してください。

```yaml
# 良い例
literal_example: |
  This example is an example of literal block scalar style in YAML.
  It allows you to split a string into multiple lines.
folded_example: >
  This example is an example of a folded block scalar style in YAML.
  It allows you to split a string into multi lines, however, it magically
  removes all the new lines placed in your YAML.

# 悪い例
literal_example: "This example is an example of literal block scalar style in YAML.\nIt allows you to split a string into multiple lines.\n"
folded_example_same_as: "This example is an example of a folded block scalar style in YAML. It allows you to split a string into multi lines, however, it magically removes all the new lines placed in your YAML.\n"
```

基本的には、末尾の改行の扱いを指定しないオペレータ（`|`、`>`）を使用してください。特別な処理が必要な場合のみ、ストリップオペレータ（`|-`、`>-`：末尾の改行を削除）やキープオペレータ（`|+`、`>+`：末尾の改行を保持）を使用してください。

## Home Assistant YAML

### デフォルト値

設定オプションがデフォルト値を使用している場合、そのオプションは例に含めないでください。ただし、そのオプションについて説明する場合は例外です。

例えば、オートメーションの `condition` オプションはオプションであり、デフォルトでは空のリスト `[]` です。

```yaml
# 良い例
- alias: "Test"
  triggers:
    - trigger: state
      entity_id: binary_sensor.motion

# 悪い例
- alias: "Test"
  triggers:
    - trigger: state
      entity_id: binary_sensor.motion
  condition: []
```

### 文字列（続き）

前述のように、文字列はダブルクォートで囲むことが望ましいですが、以下の値タイプは例外とし、可読性を高めるために引用符を省略できます：

- エンティティID（例：`binary_sensor.motion`）
- エンティティ属性（例：`temperature`）
- デバイスID
- エリアID
- プラットフォームタイプ（例：`light`、`switch`）
- 条件タイプ（例：`numeric_state`、`state`）
- トリガータイプ（例：`state`、`time`）
- アクション名（例：`light.turn_on`）
- デバイスクラス（例：`problem`、`motion`）
- イベント名
- 限られた値のみを受け付けるハードコードされた値（例：オートメーションの `mode`）

```yaml
# 良い例
actions:
  - action: notify.frenck
    data:
      message: "Hi there!"
  - action: light.turn_on
    target:
      entity_id: light.office_desk
      area_id: living_room
    data:
      transition: 10

# 悪い例
actions:
  - action: "notify.frenck"
    data:
      message: Hi there!
```

### サービスアクションターゲット

エンティティIDに対してサービスアクションを実行する場合、3つの方法があります：

1. アクションレベルのプロパティとして指定
2. サービスアクションコールのデータの一部として送信
3. サービスアクションターゲットのエンティティとして指定

サービスアクションターゲットは最も現代的な方法であり、エンティティ、デバイス、エリアをターゲットにできるため、最も柔軟で推奨される方法です。

```yaml
# 良い例
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
  - action: light.turn_on
    target:
      area_id: living_room
      entity_id: light.office_desk
      device_id: 21349287492398472398

# 悪い例
actions:
  - action: light.turn_on
    entity_id: light.living_room
  - action: light.turn_on
    data:
      entity_id: light.living_room
```

### スカラー値またはスカラー値のリストを受け付けるプロパティ

単一の値またはスカラー値のリストを受け付けるプロパティには、以下のルールが適用されます：

- 複数の値をカンマ区切りの単一文字列として指定しない
- リストを使用する場合はブロックスタイルを使用する
- 単一の値のリストは使用しない
- 単一のスカラー値の使用は許可される

```yaml
# 良い例
entity_id: light.living_room
entity_id:
  - light.living_room
  - light.office

# 悪い例
entity_id: light.living_room, light.office
entity_id: [light.living_room, light.office]
entity_id:
  - light.living_room
```

### マッピングまたはマッピングのリストを受け付けるプロパティ

`condition`、`action`、`sequence` などのプロパティは、単一のマッピングまたはマッピングのリストを受け付けます。

このような場合、たとえ単一のマッピングを渡す場合でも、マッピングのリストを使用してください。これにより、項目を追加できることが理解しやすくなり、自分のコードに単一の項目をコピー＆ペーストしやすくなります。

```yaml
# 良い例
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room

# 悪い例
actions:
  action: light.turn_on
  target:
    entity_id: light.living_room
```

### テンプレート

Home Assistantのテンプレートは強力ですが、経験の少ないユーザーにとっては混乱したり理解しにくかったりする場合があります。そのため、純粋なYAMLバージョンが利用可能な場合は、テンプレートの使用を避けるべきです。

```yaml
# 良い例
conditions:
  - condition: numeric_state
    entity_id: sun.sun
    attribute: elevation
    below: 4

# 悪い例
conditions:
  - condition: template
    value_template: "{{ state_attr('sun.sun', 'elevation') < 4 }}"
```

#### クォーティングスタイル

テンプレートは文字列であるため、ダブルクォートで囲みます。その結果、テンプレート内ではシングルクォートを使用します。

```yaml
# 良い例
example: "{{ 'some_value' == some_other_value }}" 

# 悪い例
example: '{{ "some_value" == some_other_value }}'
```

#### テンプレート文字列の長さ

テンプレート内の長い行は避け、複数行に分割して何が起こっているかを明確にし、読みやすくしてください。

```yaml
# 良い例
value_template: >-
  {{
    is_state('sensor.bedroom_co_status', 'Ok')
    and is_state('sensor.kitchen_co_status', 'Ok')
    and is_state('sensor.wardrobe_co_status', 'Ok')
  }}

# 悪い例
value_template: "{{ is_state('sensor.bedroom_co_status', 'Ok') and is_state('sensor.kitchen_co_status', 'Ok') and is_state('sensor.wardrobe_co_status', 'Ok') }}"
```

#### 短いスタイルの条件構文

表現的な形式よりも短縮形のテンプレートを優先してください。より簡潔な構文を提供します。

```yaml
# 良い例
conditions: "{{ some_value == some_other_value }}" 

# 悪い例
conditions:
  - condition: template
    value_template: "{{ some_value == some_other_value }}"
```

#### フィルター

フィルターパイプマーカー `|` の周りにはスペースが必要です。これにより読みやすさが不明確になる場合は、追加の括弧の使用をお勧めします。

```yaml
# 良い例
conditions:
  - "{{ some_value | float }}" 
  - "{{ some_value == (some_other_value | some_filter) }}" 

# 悪い例
conditions:
  - "{{ some_value == some_other_value|some_filter }}" 
  - "{{ some_value == (some_other_value|some_filter) }}"
```

#### 状態と状態属性へのアクセス

ヘルパーメソッドが利用可能な場合は、states オブジェクトを直接使用しないでください。

例えば、`states.sensor.temperature.state` ではなく、`states('sensor.temperature')` を使用してください。

```yaml
# 良い例
one: "{{ states('sensor.temperature') }}"
two: "{{ state_attr('climate.living_room', 'temperature') }}"

# 悪い例
one: "{{ states.sensor.temperature.state }}"
two: "{{ states.climate.living_room.attributes.temperature }}"
```

これは `states()`、`is_state()`、`state_attr()`、`is_state_attr()` に適用され、エンティティがまだ準備できていない場合（例：Home Assistant起動時）のエラーやエラーメッセージを避けるためです。

## Home Assistant MCP Server

### 概要

Home Assistant MCP (Model Context Protocol) Serverは、KiroからHome Assistantインスタンスに直接アクセスし、操作するためのツールです。このツールを使用することで、以下のような操作が可能になります：

- エンティティの状態取得と制御
- オートメーション、スクリプト、シーンの管理
- ダッシュボードの作成と更新
- デバイスとエリアの管理
- 統計データと履歴の取得
- システム情報の確認

### 利用可能なツール

MCP Serverは多数のツールを提供していますが、主要なものは以下の通りです：

#### エンティティ操作
- `ha_get_state`: エンティティの状態を取得
- `ha_call_service`: サービスを呼び出してエンティティを制御
- `ha_search_entities`: エンティティを検索
- `ha_get_overview`: システム全体の概要を取得

#### 設定管理
- `ha_config_get_automation`: オートメーション設定を取得
- `ha_config_set_automation`: オートメーションを作成・更新
- `ha_config_get_script`: スクリプト設定を取得
- `ha_config_set_script`: スクリプトを作成・更新
- `ha_config_set_helper`: ヘルパーエンティティを作成・更新

#### ダッシュボード管理
- `ha_config_list_dashboards`: ダッシュボード一覧を取得
- `ha_config_get_dashboard`: ダッシュボード設定を取得
- `ha_config_set_dashboard`: ダッシュボードを作成・更新
- `ha_get_dashboard_guide`: ダッシュボード設定ガイドを取得
- `ha_get_card_documentation`: カード種類のドキュメントを取得

#### データ取得
- `ha_get_history`: エンティティの履歴データを取得
- `ha_get_statistics`: 長期統計データを取得
- `ha_get_logbook`: ログブックエントリを取得

#### テンプレート
- `ha_eval_template`: Jinja2テンプレートを評価

### 使用例

#### エンティティの状態確認

```
ha_get_state(entity_id="sensor.living_room_temperature")
```

#### ライトの制御

```
ha_call_service(
  domain="light",
  service="turn_on",
  entity_id="light.living_room",
  data={"brightness_pct": 75, "color_temp_kelvin": 2700}
)
```

#### オートメーションの作成

```
ha_config_set_automation(
  config={
    "alias": "Motion Light",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion", "to": "on"}],
    "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hallway"}}]
  }
)
```

#### テンプレートの評価

```
ha_eval_template(template="{{ states('sensor.temperature') | float }}")
```

### ベストプラクティス

1. **エンティティIDの確認**: 操作前に `ha_search_entities` や `ha_get_overview` でエンティティIDを確認する
2. **設定の取得**: 既存の設定を変更する場合は、まず `ha_config_get_*` で現在の設定を取得する
3. **テンプレートのテスト**: 複雑なテンプレートは `ha_eval_template` で事前にテストする
4. **ドキュメントの参照**: 不明な点は `ha_get_domain_docs` や `ha_get_dashboard_guide` でドキュメントを確認する
5. **バックアップ**: 重要な変更を行う前は `ha_backup_create` でバックアップを作成する

### 注意事項

- MCP Serverを使用するには、Home Assistantインスタンスへの接続設定が必要です
- 一部の操作には管理者権限が必要な場合があります
- 設定変更後は、必要に応じてHome Assistantの再起動や設定の再読み込みが必要です
- 機密情報（トークン、パスワードなど）は適切に管理してください
