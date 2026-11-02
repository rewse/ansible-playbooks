# 床暖房operation status双方向同期 設計

## 目的

`switch.living_room_floor_heater_operation_status`と`switch.study_floor_heater_operation_status`の状態を双方向に同期する。一方の状態が変わってから10秒間その状態を維持し、その時点でもう一方の状態が異なる場合に同じ状態へ変更する。

## 構成

既存の床暖房制御と同じ`roles/homeassistant/files/automations-living-room-climates.yaml`に自動化を1件追加する。自動化には、各スイッチのオンとオフに対応するstateトリガーを計4件定義する。各トリガーは対象スイッチが変更後の状態を10秒間連続して維持した場合に発火する。

アクションはトリガーIDで分岐し、同期先の状態が異なる場合だけ`switch.turn_on`または`switch.turn_off`を実行する。`mode: queued`と`max: 4`を設定し、逆方向のトリガーが同時に成立しても操作を直列化する。先に処理されたトリガーが両スイッチを同じ状態にし、後続処理は状態条件を満たさなくなるため操作しない。

## 動作

| 10秒後の状態 | 動作 |
| --- | --- |
| living_roomがオン、studyがオフ | studyをオンにする |
| living_roomがオフ、studyがオン | studyをオフにする |
| studyがオン、living_roomがオフ | living_roomをオンにする |
| studyがオフ、living_roomがオン | living_roomをオフにする |
| 両方が同じ状態 | 何もしない |
| 起点側が10秒以内に別の状態へ変化 | トリガーが成立しないため何もしない |
| 同期先がunknownかunavailable | オンまたはオフの状態条件を満たさないため何もしない |

同期処理で状態が変わった側でも逆方向のトリガーが開始するが、10秒後には同期先がすでに同じ状態のため操作しない。操作が往復するループは発生しない。

## 配備と検証

Ansibleの既存`automation : Copy files`タスクで対象ファイルを`/srv/homeassistant/config/automations`へ配備する。配備前にYAMLとAnsibleの構文を検証する。配備後はHome Assistantの自動化を再読み込みし、自動化エンティティが有効であることと設定内容を確認する。床暖房を実際にオンまたはオフにする動作試験は、意図しない暖房操作を避けるため自動では行わない。
