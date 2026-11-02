# Model Y 最終フルチャージ日時の記録

## 目的

`binary_sensor.model_y_battery_full_charge_due` は `sensor.model_y_battery_max_30_days`(30 日間の最大値を出す statistics センサー)で判定している。この方式では最後にフルチャージした日時が分からない。日時を記録し、判定をその日時ベースに変える。

## ゴールと非ゴール

- ゴール: 最後に `sensor.model_y_battery` が 100 になった日時を Home Assistant 上で確認できる
- ゴール: その日時から 30 日経つと binary_sensor が on になり、既存のアラームが通知する
- 非ゴール: TeslaMate の DB から直接日時を読むこと
- 非ゴール: 通知の文面やアラームのトリガー条件を変えること

## アプローチ

- A. `input_datetime` に日時を保存し、オートメーションで更新する。Roomba の `input_datetime.roomba_combo_next` と同じ作りになる。TeslaMate で調べた日時を UI から初期値として入れられ、手で修正もできる(採用)
- B. トリガー型テンプレートセンサーに timestamp を保存する。定義が `templates.yaml` だけで済むが、初期値を入れる手段がなく、デプロイ直後から次のフルチャージまで判定できない
- C. TeslaMate の DB を SQL センサーで読む。DB の接続情報を Home Assistant に渡すことになり、可動部分が増える。また「`sensor.model_y_battery` が 100 になった瞬間」という基準とずれる

利用者は A を選んだ。

## 決めたこと

- フルチャージの定義は、`sensor.model_y_battery` が 100 になった瞬間とする(利用者の決定)
- `input_datetimes.yaml` に `model_y_battery_last_full_charge`(日付と時刻あり)を追加する
- `automations-tesla.yaml` にオートメーションを追加する。`sensor.model_y_battery` が 100 になったら、`input_datetime.model_y_battery_last_full_charge` に `now()` を書き込む
- binary_sensor は、`now()` が最終フルチャージ日時から 30 日以上経っていれば on にする
- `sensors.yaml` の `sensor.model_y_battery_max_30_days` は不要になるので削除する
- `roles/homeassistant/tests/model_y_full_charge_due.yml` を新しい構成に合わせて書き換える
- デプロイ時に、TeslaMate で調べた最終フルチャージ日時を初期値として入れる

## 実装者の判断に任せること(Kiro の判断)

- トリガーは `numeric_state` の `above: 99` を使う。`sensor.model_y_battery` は整数値なので 100 と同じ意味になり、文字列比較を避けられる
- binary_sensor の `availability` は、`input_datetime` の `timestamp` 属性が数値かどうかで判定する。値が未設定(1970-01-01)のときは on になりうるが、デプロイ時に初期値を入れるので許容する
- 再起動のたびに通知が繰り返されないよう、アラームの `from: "off"` は維持する
- デプロイは `input_datetime` を先に反映して初期値を入れ、そのあと binary_sensor の変更を反映する。未設定のまま binary_sensor が off から on に変わると誤通知が出るため
- 100 のまま数日置いても、記録されるのは最初に 100 になった日時になる。「100 になった瞬間」という定義どおりとする
