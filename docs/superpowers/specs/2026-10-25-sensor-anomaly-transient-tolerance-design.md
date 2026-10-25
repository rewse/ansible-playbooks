# 温湿度計 anomaly の一時欠測への耐性 設計

## 目的

HA の再起動や Matter サーバーの数分の停止で、各部屋の `*_thermometer_anomaly`、`*_hygrometer_anomaly`、`*_fault` が on になり、アラームが飛び、Climate 制御が 1 時間止まるのをなくす。2026-10-25 の matterjs-server への切り替えでは約 2 分の欠測で 3 部屋の 12 個が on になり、復旧まで 1 時間かかった。

## 現状

- anomaly（6 個）は、主センサーの非数値、主センサーと副センサーの範囲外（温度 5℃ 未満か 40℃ 超、湿度 1% 未満か 99% 超）、主センサーの 2 時間未報告、disagreement の OR で、`delay_off: 1 hour` を持つ。どれかが真になると即座に on になる
- disagreement（6 個）は 1 時間平均の差が温度 1.5℃、湿度 10 ポイントを超えたら真で、`delay_on: 2 hours` を持ち、`delay_off` はない
- fault（6 個）は anomaly か副センサーの 24 時間欠測の OR で、遅延はない。off から on への遷移でアラームを通知し、Climate 制御 automation は fault が off であることを条件にする
- Climate 制御 automation は `float(states(...))` で読み値を使うので、主センサーが `unavailable` のあいだはテンプレートがエラーになり動かない
- recorder の 1 時間統計（Aqara は 2021-10 から、SwitchBot は 2024-07 から）では、範囲外になった時間帯は一度もない。最も外れた値でも温度 12.0〜32.7℃、湿度 18.4〜87%

## ゴール

- 10 分未満の主センサーの欠測では anomaly も fault も on にならず、アラームも飛ばない
- anomaly の条件が解消したら、anomaly と fault はすぐ off になる
- disagreement のばたつきは従来どおり 1 時間の正常継続で抑える

## 範囲外

- 範囲外の判定は削除する（ユーザーの判断、YAGNI）。起きたことがなく、起きても disagreement が拾える
- fault の副センサー 24 時間欠測条件、アラームと Climate 制御 automation、しきい値（2 時間、1.5℃、10 ポイント、24 時間）は変えない

## 方式

| 方式 | 内容 | 判断 |
|---|---|---|
| A | anomaly から `delay_off` を外して `delay_on: 10 minutes` を付け、`delay_off: 1 hour` を disagreement に移す | 採用 |
| B | anomaly の非数値条件を「非数値かつ `last_changed` から 10 分以上」に書き換え、遅延は付けない | 不採用。A と同じ結果になるが、6 個のテンプレートに時刻計算が増える |
| C | 主センサーの非数値条件を削除し、長い欠測は 2 時間未報告の条件に任せる | 不採用。欠測中に連携が `unavailable` を書き直すと `last_reported` が更新され、未報告の条件が働かない。働いても検知は 2 時間後になる |

A では 2 時間未報告と disagreement の検知が 10 分ずつ遅れる（実質 2 時間 10 分）。どちらも時間単位の判定なので影響はない。HA の起動時は anomaly の前回の状態が復元され、主センサーが 10 分以内に数値に戻れば off のまま変わらない。

`thermometer-fault-detection` の要件「すべての異常条件が解消した状態が 1 時間継続した場合に自動復旧する」は、disagreement だけに適用するよう改める。

## 変更

`roles/homeassistant/files/templates.yaml` の 3 部屋分を変える。

- anomaly（`binary_sensor.<room>_thermometer_anomaly`、`binary_sensor.<room>_hygrometer_anomaly`）: state を主センサーの非数値、2 時間未報告、対応する disagreement の 3 条件の OR にする。範囲外の条件と、それだけに使う `secondary` 変数を消す。`delay_off` を外し、`delay_on: minutes: 10` を付ける。コメントを新しい挙動に合わせる
- disagreement（`binary_sensor.<room>_temperature_disagreement`、`binary_sensor.<room>_humidity_disagreement`）: `delay_off: hours: 1` を足す。`delay_on: hours: 2` はそのまま
- fault: 変えない

`roles/homeassistant/tests/thermometer_fault_detection_room.yml` と `hygrometer_fault_detection_room.yml` の契約を合わせる。anomaly は `delay_on.minutes == 10` で `delay_off` を持たず、範囲外の比較を含まず、非数値、未報告、disagreement の各条件を含むこと。disagreement は `delay_on.hours == 2` と `delay_off.hours == 1` を持つこと。

## 反映と検証

- pre-commit と `uv run --with pytest --with ansible-core pytest tests` を通す。ロールのテスト playbook も通す
- 反映前に、副センサー 6 個が数値であることを確かめる。`--tags homeassistant_configuration` は HA を再起動する
- 反映で HA が再起動したあと、12 個の anomaly と fault が off のままで、アラームが届かないことを確かめる。これが一時欠測への耐性の実機での確認になる

## 設計時に決めたこと

- 欠測を許す時間を 10 分にした。HA の再起動と Matter サーバーの再起動はどちらも数分で終わる
- 方式 A を選んだ
