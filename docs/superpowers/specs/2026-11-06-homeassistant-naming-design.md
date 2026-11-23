# Home Assistant のデバイス名とエンティティ ID の統一 設計

## 目的

Home Assistant のデバイス名とエンティティ ID の付け方がそろっていない。エリア名を名前に含めるかどうか、修飾語の位置と書き方、略語、アポストロフィの記号がまちまちで、ID を見ても何を指すのか分からないものがある。利用者は以前からこれを気にしており、2026.11 の命名方式の変更を機に、家全体を一つのルールにそろえる。

2026.11 では、表示名をエリア、デバイス、エンティティの部品から組み立てるようになる。名前をそれぞれの部品に一度だけ付け、ほかの部品の名前を繰り返さない前提である。2026.8 からは、新しく作られるエンティティ ID も同じ部品から `<area>_<device>_<entity>` の形で作られる。今回のルールはこの標準に合わせ、今後追加するデバイスでも手作業なしで ID がそろうようにする。

## 現状

2026-11-06 時点の Home Assistant は 2026.10.4 である。登録されているエンティティは 1,840 個で、そのうちエリアを持つ 1,137 個のうち ID がエリア名で始まるのは 578 個しかない。末尾に `_2` などの連番が付いた ID は 85 個ある。

- エリアを持つデバイス 178 台のうち少なくとも 85 台は、デバイス名がエリア名で始まる（例: `Living Room Thermometer`）
- リビングは壁で仕切られていない一つの部屋だが、デスク側のデバイスを `Study` と呼ぶもの、`Living Room` と呼ぶもの、両側をまとめて `Living Area` と呼ぶものが混在する（例: `light.study_downlights`、`light.living_area_downlights`）。`Study` というエリアはなく、これらはすべて `living_room` エリアにある
- エリア ID `bedroom` の表示名は `Mom’s Room` で、ID には `moms_room`、`mom_s_room`、`eufy_mom` が混在する
- アポストロフィは `Dad’s`（U+2019）が 154 台、`Dad's`（ASCII）が 29 台、`Mom’s` が 113 台、`Mom's` が 28 台ある。Home Assistant の slugify は `Dad's Room` を `dad_s_room`、`Dad’s Room` を `dads_room` にする
- 修飾語は名前の後ろに付けるもの（`Plug East`、`Window Sensor N`、`Presence Sensor E`、`Lock Top`）、前に付けるもの（`Left Light`、`Center Plug`）、連番（`Floor Heater 2`）が混在し、方角は `East` と `E` が混在する
- ID 中の略語は `temp` 83 回に対し `temperature` 50 回、`diff` 84 回に対し `difference` 12 回、`max` 48 回に対し `maximum` 11 回、`min` 44 回に対し `minimum` 8 回である。略語はほとんどが自作の `input_number` で、インテグレーションが付ける名前は略さない
- デバイス名に型番や製品名を使ったものがある（`Aventage`、`regza`、`Roomba Combo`、`switchbothub`、`eufy-ent`）
- 加湿器や扇風機は、家電そのものを表すデバイスなしのテンプレートエンティティ、オンオフを判定するプラグ、ボタンを押す SwitchBot の三つでできている。SwitchBot のデバイス名が家電と同じ `Humidifier` や `Fan` になっており、扇風機では SwitchBot 側の `fan` エンティティがテンプレートとぶつかって `fan.living_room_fan_2` になっている
- このリポジトリの `roles/homeassistant` は 655 種類のエンティティ ID を延べ約 1,300 か所で参照している

## ゴール

- 対象のデバイス名とエンティティ ID が下の命名ルールに従っている
- 新しく追加したデバイスのエンティティ ID が、Home Assistant の自動生成のままでルールに合う
- 改名の前後でオートメーション、スクリプト、テンプレート、通知、音声アシスタント、HomeKit、ダッシュボードが同じように動く
- 改名したデバイスのエンティティの履歴と長期統計が引き継がれている
- YAML で定義したヘルパーの値（しきい値、選択肢の選択状態、日時、オンオフ）が改名の前後で変わらない

## 範囲外

- エリアを持たないシステム系のエンティティ（Backup、Sun、更新通知など）
- ネットワーク機器（UniFi のスイッチや AP など）のデバイスとエンティティ
- エリアを設定していないデバイス（車、スマートフォンなど）と `person` のエンティティ。`<area>_` で始められないため対象にしない（実装者の判断）
- YAML で定義したヘルパーの履歴。利用者は見返さないため、切れてよい
- `restroom` エリアの整理。このエリアにはデバイスもエンティティもないため、改名の対象もない
- Alexa の `entity_config` に書いた日本語の呼び名。ID の付け替えは行うが、呼び名は変えない
- `alexa.yaml` の呼び名「ママの部屋の南側のの窓」のタイポ修正。音声コマンドとして使われている可能性があるため、利用者が別に判断する

## やってはいけないこと

- 改名の途中で、新旧の ID が混ざったまま本番を長く放置すること。部屋ごとに分けて進める場合も、一つの部屋は Home Assistant とリポジトリで同じ日に切り替える
- デバイスに属するエンティティの ID を、履歴を捨てる方法（エンティティの削除と再作成）で変えること
- YAML で定義したヘルパーのキーを変えるときに、今の値を控えずに適用すること。`initial` を書いていないため、キーを変えると値が初期値に戻る
- デバイス名からエリア名を外したのに、通知文が `friendly_name` のままで部屋名を失うこと

## 命名ルール

### エリア

- エリアは部屋ごとに一つ作る。壁で仕切られていない空間はエリアを分けず、場所の違いはデバイス名の修飾語で表す。リビングのデスク側も `Living Room` エリアのままとし、`Study` と `Living Area` はエリア名にもデバイス名にも使わない
- エリア名のアポストロフィは ASCII の `'` にする（`Dad's Room`、`Mom's Room`）。打ちやすさを優先し、その結果 ID が `dad_s_room`、`mom_s_room` になることを受け入れる
- エンティティ ID の生成にはエリア ID ではなくエリア名が使われるため、エリアは作り直さず名前だけ変える。エリア ID（`dads_room`、`bedroom`）は内部に残るが ID には現れない

### デバイス名

- デバイス名にエリア名を含めない。エリアは Home Assistant が表示時に足す
- デバイス名は型番や製品名ではなく一般名称にする（`AV Receiver`、`TV`、`Robot Vacuum`、`Camera`）。メーカーと型番はデバイスの属性に任せる
- 同じエリアに同じ種類のデバイスが一つしかなければ、修飾語を付けない（`Thermometer`）
- 同じエリアに同じ種類のデバイスが複数あるときは、場所を表す修飾語を名前の末尾に付ける（`Floor Heater North`、`Window Sensor North`）
- リビングはデスク側を `North`、反対側を `South` とする。今 `Study` と呼んでいるデバイスは `North` 側になる
- 同じ場所に置いた同じ種類のデバイスを役割で区別するときは、修飾語 `Primary` と `Secondary` を末尾に付ける。故障検知（`templates.yaml` の `*_disagreement`、`*_fault`）で比べる温湿度計の組がこれに当たり、Dad's Room と Mom's Room は Aqara を `Thermometer Primary`、SwitchBot Meter を `Thermometer Secondary` とする。Balcony は故障検知の対象ではないが同じ規則に従い、今 `sensor.balcony_temperature` を出している SwitchBot Outdoor Meter を `Thermometer Primary`、SwitchBot Meter を `Thermometer Secondary` とする。リビングの SwitchBot Hub 2 は故障検知の secondary だが、`Hub` という別の種類として呼べて名前がぶつからないため、`Thermometer` と `Hub` のままにする
- 修飾語は略さない。方角は `North`、`Northeast` のように一語で書く。方角以外の修飾語（`Left`、`Right`、`Top`、`Bottom`、`Center`）も末尾に付ける（`Light Left`、`Lock Top`）
- 連番（`2`）は使わず、修飾語に置き換える
- 家電を補助デバイスで動かしているときは、補助デバイスを `<家電名> <役割>` と名付ける。役割は `Plug`（電源の判定と遮断）と `Switch`（SwitchBot でボタンを押す）とする。補助デバイスがプラグ一つだけの家電も `<家電名> Plug` とする
- 補助デバイスをまとめて家電そのものを表すテンプレートエンティティには、修飾語なしの家電名を付ける（`Humidifier`、`Fan`）
- 二つの場所にまたがるものをまとめるグループエンティティには、修飾語を付けない（両側のダウンライトをまとめた `light.living_room_downlights`）

### エンティティ名

- インテグレーションが付けた名前（`Temperature`、`Power` など）はそのまま使う
- 自分で付ける名前は略語を使わない（`Temperature`、`Difference`、`Maximum`、`Minimum`）。略語のほうが一般名称であるもの（`AC`、`AVR`、`CO2`、`PM2.5`、`TV`）はそのまま使う
- デバイスそのものを表すエンティティ（プラグのスイッチなど）は「Main entity of the device」をオンにする

### エンティティ ID

- デバイスに属するエンティティの ID は、2026.8 以降の標準形式 `<area>_<device>_<entity>` で Home Assistant に生成させたものにする

  ```
  sensor.living_room_thermometer_temperature
  switch.living_room_floor_heater_north_operation_status
  switch.living_room_humidifier            # appliance (template)
  switch.living_room_humidifier_plug       # plug
  switch.living_room_humidifier_switch     # SwitchBot
  fan.living_room_fan                      # appliance (template)
  fan.living_room_fan_switch               # SwitchBot
  ```

- デバイスに属さない自作のエンティティ（オートメーション、スクリプト、ヘルパー、テンプレートエンティティ）も、部屋に関わるものはエリア名で始め、同じ略語のルールに従う。エリアを割り当て、表示名からはエリア名を外す（`name: "Humidity Maximum Difference"`）。表示名にエリア名を残すと、2026.11 の表示でエリア名が二重になるため（実装者の判断）

  ```
  input_number.living_room_temperature_maximum_difference_present_summer_midnight
  ```

- YAML で定義したヘルパーとスクリプト（`input_numbers.yaml` 160 個、`input_selects.yaml` 31 個、`input_datetimes.yaml` 13 個、`input_booleans.yaml` 8 個、`scripts.yaml` 6 個）は、キーがそのまま ID になる。キーごと書き換えて、キーと ID を一致させる。Home Assistant からは別のエンティティとして作り直された扱いになり、履歴は切れ、値は初期値に戻る。適用前に今の値を控え、適用後にスクリプトで入れ直す。古いエンティティの登録情報が残る場合は消す

- 一つのデバイスが同じ種類のエンティティを複数持ち、`switch.living_room_fan_switch_switch` のような重複や連番が生じるときは、エンティティ名を見直して避ける

## 方式

| 方式 | 内容 | 判断 |
|---|---|---|
| マッピング表で一括適用 | API でデバイス、エンティティ、エリアを取り出し、ルールに沿った新しいデバイス名と ID を「旧 → 新」の CSV にする。利用者が CSV を確認して修飾語を埋め、API で一括適用し、同じ CSV でリポジトリを一括置換する | 採用。千件を超える変更をレビューでき、CSV から逆向きに戻せる |
| UI で部屋ごとに変更 | 2026.8 の ID 再生成ボタンで一部屋ずつ変える | 不採用。千回を超える操作になり、リポジトリの置換と足並みをそろえにくい |
| マッピング表を部屋ごとに適用 | 一括適用と同じ仕組みで、適用とデプロイを部屋単位に分ける | 一括適用の中で使う。CSV に部屋の列を持たせ、部屋単位で適用や切り戻しができるようにする |

## 進め方

1. Home Assistant を 2026.11 に更新する（2026.11.2 で完了。結果は「2026.11 更新後に確かめたこと」）
2. `roles/homeassistant/files/automations-alarm.yaml` の通知文で使っている `trigger.to_state.attributes.friendly_name` の 5 か所を、`area_name()`、`device_name()`、`entity_name()` を使う形に置き換えてデプロイする。2026.11 以降も `friendly_name` にはエリア名が入らないため、デバイス名からエリア名を外す前に済ませる。Main entity では `entity_name()` が空文字を返すため、エリア、デバイス、エンティティのうち空でないものだけを空白でつなぐ
3. マッピング表を作り、利用者がレビューする
4. エリア名、デバイス名、エンティティ ID を API で変え、同じ日にリポジトリの参照を置き換えてデプロイする
5. Home Assistant の外で ID を参照しているものを直す。Alexa は再検出して定型アクションを確かめる。HomeKit ブリッジは ID が変わったアクセサリが追加し直しになるため、ホームアプリでの部屋の割り当てとオートメーションを確かめる。`homekit.yaml` の各エンティティには `entity_config` で部屋名を含む名前を付け、デバイス名からエリア名を外しても「AC」「CO2」のような同じ名前が並ばないようにする。ストレージ管理のダッシュボードとエネルギーダッシュボードの参照を置き換える。これら以外に ID を参照しているもの（Companion アプリのウィジェット、ショートカット、ほかのリポジトリ）はない
6. 動作を確かめる。Home Assistant のログと Repairs に、存在しないエンティティへの参照が出ていないことを確かめる

## 2026.11 更新後に確かめたこと

2026-11-23 に 2026.11.2 で確かめた。

- エンティティ ID の形式は設定が保存されておらず、標準の「エリア、親デバイス、デバイス、エンティティ」の順で生成される。エリアの部分には `helpers/entity_registry.py` の `_async_get_full_entity_name` がエリア名（`area.name`）を使う。デバイスの「Recreate entity IDs」は、この形式で ID を作り直す
- エンティティ部分には、利用者が付けた名前があればそれを、なければインテグレーションの名前を使う。名前が空の Main entity では、エンティティ部分が省かれる
- 「Recreate entity IDs」はデバイス単位の操作で、デバイスに属さないエンティティの ID は作り直さない。これらは手で変える。YAML で定義したヘルパーはキーで ID が決まるため、方針は変わらない
- `entity_name()` は Main entity で空文字を返す。例: `switch.living_room_humidifier_plug` は `entity_name()` が空、`device_name()` が `Living Room Humidifier Plug`、`area_name()` が `Living Room`
- 子デバイスは作られていない。デバイスレジストリの `child_devices` は空で、デバイスは 288 台のまま
- UI で名前を付けていたデバイスのエンティティ 109 個は、ほとんどがデバイス名を外した形（`Power`、`Identify` など）に移行された。デバイス名で始まらない名前が残り、表示が崩れるものは次のとおりで、マッピング表で直す
  - Frigate のカウント 8 個（`sensor.eufy_dad_person_count` の `Eufy-Dad Person Count` など）。デバイス名と重なって `Dad's Room Camera Eufy-Dad Person Count` のように表示される
  - `light.dads_room_footlight`。エンティティ名が `Footlight` で、デバイス名が `Dad’s Room Floorlight`
  - `sensor.dads_room_switchbot_meter_temperature`。エンティティ名が `Temeperature` で、綴りを誤っている
- 上の Frigate のカウントでは、`friendly_name` が移行前の `Eufy-Dad Person Count` のまま残り、新しい表示名と一致しない

## 実装者に任せること

- マッピング表の生成方法、列の構成、置き場所
- API 呼び出しの順序（エリア名、デバイス名、エンティティ ID）とスクリプトの言語
- リポジトリの一括置換の方法。部分一致による誤置換（`switch.living_room_humidifier` が `switch.living_room_humidifier_plug` の一部に当たるなど）を防ぐこと
- 部屋ごとに分けるかどうかとその順番
- `roles/homeassistant/tests` のテストの更新
