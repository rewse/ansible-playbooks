# 副センサー欠測からの即時復旧設計

## 目的

副センサー（SwitchBot）の欠測が解消したら、温度計故障と湿度計故障をすぐに解除し、自動 Climate 制御を再開する。現在は副センサーが 24 時間 `unavailable` になると fault が on になり、センサーが戻ってからも `delay_off: 1 hour` のために制御が 1 時間止まる。2026-10-25 に Dad’s Room でこれが起き、室温 28℃ でもエアコンが自動で入らなかった。

## 背景

`delay_off` は `thermometer-fault-detection` の要件「すべての異常条件が解消した状態が 1 時間継続した場合に自動復旧する」から来ており、異常のばたつきを抑える。平滑化後の差（disagreement）や主センサーの一時的な異常値にはこの抑制が効く。副センサーの欠測条件は再発までに 24 時間の欠測を要するので、復帰直後に再び切れても fault は再発せず、1 時間待つ意味がない。

## 目標と非目標

- 目標: 副センサーの非数値 24 時間継続と 24 時間未報告の 2 条件だけが原因の fault を、条件解消と同時に off にする。
- 目標: 主センサー、副センサーの範囲外、disagreement による fault は従来どおり 1 時間の正常継続で復旧する。
- 非目標: しきい値（24 時間、2 時間、1.5℃、10 ポイント）の変更。
- 非目標: fault を参照する automation や通知の変更。

## 検討した方式

1. 採用: 遅延付きの判定と遅延なしの判定に分ける。主センサー、副センサーの範囲外、disagreement の条件を新しい `binary_sensor.<room>_thermometer_reading_fault` と `binary_sensor.<room>_hygrometer_reading_fault` へ移し、`delay_off: 1 hour` を付ける。既存の `*_thermometer_fault` と `*_hygrometer_fault` は、reading fault が on か副センサー欠測条件が真かの OR とし、遅延を外す。entity ID は変わらないので、automation、アラーム、ダッシュボードは影響を受けない。
2. 不採用: `delay_off` 全体を 10 分程度へ短縮する。変更は小さいが、disagreement のばたつき抑制も弱まり、元の要件の意図から外れる。
3. 不採用: `delay_off` をテンプレートにして原因に応じて変える。off へ遷移する時点ではすべての条件が偽なので、原因を判別できない。

## 対象

Dad’s Room、Living Room、Mom’s Room の 3 部屋に適用する（担当者判断）。3 部屋とも同じ構造で副センサーの 24 時間条件を持ち、テストも 3 部屋共通の契約で検証しているため、Dad’s Room だけ変えると構造が分かれる。追加 entity は 1 部屋 2 個、計 6 個。reading fault の名前は既存 fault の名前に `Reading` を挟んだもの（例: `Dad’s Room Thermometer Reading Fault`）とし、`device_class: problem` を付ける（担当者判断）。アラームは既存 fault を引き続き参照し、reading fault 単独では通知しない。

## 検証

- `roles/homeassistant/tests/thermometer_fault_detection*.yml` と `hygrometer_fault_detection*.yml` を新構造に合わせて更新する。reading fault が主センサー、範囲外、disagreement の条件と `delay_off.hours == 1` を持つこと、fault が reading fault と副センサー欠測条件を参照し `delay_off` を持たないことを確認する。
- pre-commit と pytest を実行する。
- `--tags` を絞って homeassistant の該当コンポーネントを check と apply で適用し、実機で 6 個の reading fault の状態と、既存 fault が off のままであることを確認する。
