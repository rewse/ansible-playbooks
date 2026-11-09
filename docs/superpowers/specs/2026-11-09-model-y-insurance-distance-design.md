# Model Y 保険走行距離警告 設計

## 目的

Model Y の自動車保険には保険期間 1 年あたりの走行距離条件がある。条件を超える前に気づけるよう、保険期間内の走行距離が条件の 80% に達したら Home Assistant で警告する。契約は毎年 8月26日に更新される。

## ゴール

- 保険期間内の走行距離を自動で数え、毎年 8月26日に 0 へ戻す。
- 条件距離は `input_number` で持ち、UI から変えられる。
- 80% に達したら `binary_sensor` を on にし、off→on のときに通知する。

## 非ゴール

- 期間開始時のオドメーター値の手入力と、その更新漏れの警告。utility meter が期間の区切りを持つので不要になった。
- ダッシュボードへの追加。
- 期間末の走行距離の予測。

## アプローチ

- A. 期間開始時のオドメーター値を `input_number` に手入力し、`sensor.model_y_odometer` との差を走行距離とする。更新日時は `input_datetime` に記録し、8月26日を過ぎても更新されなければ別の `binary_sensor` で警告する。毎年の手入力が要る。
- B. A と同じだが、更新の判定に `input_number` の `last_changed` を使う。Home Assistant の再起動で `last_changed` が起動時刻に変わり、警告が消えるので不適。
- C. `utility_meter` で `sensor.model_y_odometer` を数え、`cron: "0 0 26 8 *"` で毎年 8月26日 0:00 にリセットする。手入力も更新漏れの警告も要らない。値は再起動後も保持され、ソースが `unavailable` の間の走行分は値が戻ったときにまとめて加算される。

利用者は C を選んだ。手入力をなくせるため。

## 設計

- `utility_meters.yaml` に `model_y_insurance_distance`（`unique_id: sensor.model_y_insurance_distance`、`source: sensor.model_y_odometer`、`cron: "0 0 26 8 *"`、`periodically_resetting: false`）を追加する。オドメーターは減らないので、`periodically_resetting` を既定の true にしておくと、値が一時的に下がったときにソースのリセットと見なされ、戻った分のオドメーター全体が加算されて誤警告になる（実装者の判断）。
- `input_numbers.yaml` に `model_y_insurance_distance_limit`（km、`mode: box`）を追加する。
- `templates.yaml` の Model Y の節に `binary_sensor.model_y_insurance_distance_warning` を追加する。状態は `sensor.model_y_insurance_distance >= input_number.model_y_insurance_distance_limit * 0.8`。両方が数値で、条件距離が 0 より大きいときだけ available にする。
- `automations-alarm.yaml` に `automation.alarm_model_y_insurance_distance_warning` を追加する。既存の `automation.alarm_model_y_battery_full_charge_due` と同じく、`from: "off"` `to: "on"` で `notify.tats_devices` に `⚠ ALARM` を送る。メッセージには走行距離と条件距離を入れる。
- `roles/homeassistant/tests/` に `model_y_full_charge_due.yml` と同じ形式のテストを追加し、上記の構成を検証する。

## 導入手順

デプロイ後、`utility_meter.calibrate` で `sensor.model_y_insurance_distance` に現在の `sensor.model_y_odometer` の値をそのまま入れる。利用者によると、今の保険期間（2026年8月26日から）はオドメーター 0 km から始まっているので、オドメーターの値がそのまま期間内の走行距離になる。その後、条件距離を `input_number.model_y_insurance_distance_limit` に入れる。

## 実装者に任せる点

- `input_number` の `min`、`max`、`step`、アイコン。`min` は 0 とし、未設定の 0 では available にならないので誤警告しない。
- 通知文の言い回し。
- `vars/main.yml` で各ファイルがどのリストに入っているかに合わせた、反映に再起動が要るかの判断。
