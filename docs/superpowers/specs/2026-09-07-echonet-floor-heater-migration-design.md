# ECHONET Lite床暖房移行 設計

## 目的

床面温度差から床暖房の状態を推定する構成と旧SwitchBot操作経路を廃止し、ECHONET Liteのoperation statusスイッチを状態取得と操作に使用する。Living Room Floor ThermometerをHome Assistantから削除できる状態にする。

## 使用するエンティティ

- `switch.living_room_floor_heater_operation_status`
- `switch.study_floor_heater_operation_status`

両スイッチは既存の`automation.sync_living_area_floor_heater_operation_status`でオン・オフを双方向同期する。個別操作と自動化による同時操作のどちらでも、10秒後に同じ状態へ揃う。

## 廃止するエンティティ

- `binary_sensor.living_room_floor_thermometer_connectivity`
- `sensor.living_room_floor_heating_effect`
- `switch.living_area_floor_heatings`
- `switch.living_room_floor_heating`
- `switch.study_floor_heating`

`switches.yaml`と`switch: !include switches.yaml`を削除する。この削除は一回限りの移行処理としてfoxへSSHで実施し、Ansible playbookには削除タスクを残さない。`template: !include templates.yaml`の恒常管理では挿入位置を`shell_command:`の後にする。

## 自動化とスクリプト

`automation.toggle_living_area_floor_heating`では、旧groupの状態条件を新しい2スイッチへ置換し、オン・オフ操作も新しい2スイッチを直接対象にする。オン処理はどちらかがオフの場合に両方をオンにする。オフ処理はどちらかがオンの場合に両方をオフにする。床暖房スイッチの状態に対する待機は設けない。オフ判定に使う`binary_sensor.living_room_temp_high`の1時間待機は維持する。

`automation.toggle_living_room_ac_heat`の旧group参照も新しい2スイッチへ置換する。どちらかがオンなら条件を満たし、床暖房状態に対する1時間待機は設けない。

Darken Living Roomスクリプトは、新しい2スイッチのいずれかがオンなら両方をオフにする。

## Alexaとダッシュボード

Alexaには`switch.living_room_floor_heater_operation_status`だけを「リビングの床暖房」として公開する。書斎側は双方向同期自動化で追従する。

storage-modeダッシュボードでは、`switch.living_area_floor_heatings`のカードを3箇所から削除する。旧個別スイッチのカードは、それぞれ対応するECHONET Liteスイッチへ置換する。`sensor.living_room_floor_heating_effect`だけを表示する履歴グラフはカードごと削除する。

## Floor Thermometer関連設定

Floor Thermometerの接続性template binary sensorを削除する。電池低下アラームから`sensor.living_room_floor_thermometer_battery`を、Matterセンサー接続アラームから`binary_sensor.living_room_floor_thermometer_connectivity`を削除する。

Matterデバイス本体と直接生成される7エンティティは、この移行では削除しない。移行後にリポジトリ、自動化、スクリプト、ヘルパー、シーン、ダッシュボードからの参照がないことを確認し、デバイス削除は別の明示的な承認後に行う。

## 検証

実装前に、廃止対象と新しい参照関係を検査する契約テストを追加して失敗を確認する。実装後は契約テスト、Ansible構文確認、fox限定check modeを実行する。配備後はHome Assistantの設定検証と対象コンポーネントの再読み込みを行い、廃止エンティティが消え、新しいスイッチと既存同期自動化が有効であることを確認する。床暖房を実際に操作する自動テストは行わない。
