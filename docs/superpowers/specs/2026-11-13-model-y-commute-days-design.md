# Model Y 通勤日数警告 設計

## 目的

三井ダイレクト損保の使用目的「日常・レジャー使用」の条件は、通勤・通学への使用が「年間を通じて、週5日以上または月15日以上」に当たらないこととされている。「年間を通じて」が年間平均を指すのか、毎月の頻度を指すのかは公開情報からは決まらない。そこで直近30日の通勤日数を数え、15日の80%と90%に達したら Home Assistant で警告する。直近30日が常に15日未満であれば、どちらの解釈でも条件に当たらない。

## ゴール

- `sensor.model_y_geofence` が通勤先の駐車場になった日を、1日に何回出入りしても1日として数える。
- 直近30日（今日を含む）の通勤日数をセンサーで示す。
- 12日（15日の80%）と14日（13.5日以上、15日の90%）で別々に警告し、それぞれ off→on のときに通知する。

## 非ゴール

- 通勤とそれ以外の用途の区別。通勤先の駐車場に入った日は、休日でもすべて数える。安全側に倒すため。
- 保険年度（8月26日始まり）の累計日数や年間平均の算出。
- 「週5日以上」の判定。月にすると約21日で、15日より先に当たることはない。

## 通勤先の駐車場

TeslaMate のジオフェンス名は手で編集されるので、`automation.enable_tesla_sentry_at_tns_azabudai_3_chome` と同じく小文字にして比べる。

- APA Hotel & Resort Roppongi Ekihigashi
- ARK Hills Sengokuyama Mori Tower
- TNS Azabudai 3-chome

## アプローチ

- A. trigger 型テンプレートセンサーの属性に、通勤した日付のリストを持つ。テンプレートの `this` で前回のリストを読み、今日の日付を足して30日より古いものを捨てる。trigger 型テンプレートエンティティは、属性も含めて再起動時に復元される。既存の距離警告と同じ `templates.yaml` で完結する。作成時はリストが空なので、履歴から初期値を一度だけ流し込む。
- B. SQL 統合で recorder の PostgreSQL を読み、直近30日の該当ステートの日付を重複なく数える。初期値は要らないが、HA の内部スキーマに依存し、HA の更新で壊れても気づきにくい。
- C. オートメーションで日付を `input_text` に書き込む。A と同じ仕組みで、255文字の上限と別のオートメーションが増える。

history_stats は回数か時間しか数えられず、日数を数えられないので除外した。

利用者は A を選んだ。HA の更新で壊れにくく、距離警告と同じ作り方で揃えられるため。

## 設計

`templates.yaml` に trigger 型のブロックを1つ追加する。

- トリガー
  - `sensor.model_y_geofence` の状態変化（`to: null` で属性だけの変化を除く）
  - 毎日 0:00（古い日付を捨てるため）
  - Home Assistant の起動
  - イベント `model_y_commute_days_set`（初期値の流し込みと手での修正用。`dates` に `YYYY-MM-DD` のリストを渡すと、リストをそれで置き換える）
- 日付の追加条件: ジオフェンスが通勤先の駐車場のどれかで、その状態の `last_changed` の日付が今日であること。日付は HA のタイムゾーン（Asia/Tokyo）で数える。0:00 の再計算で、前日から停めたままの車を翌日の通勤として数えないためにこの条件を置く。
- 日付は `YYYY-MM-DD` の文字列で持ち、重複を除いて並べ、今日から29日前より古いものを捨てる。
- `sensor.model_y_commute_days`: 状態はリストの件数、属性 `dates` にリストを持つ。
- `binary_sensor.model_y_commute_days_80_percent`: `sensor.model_y_commute_days` が 15 × 0.8 = 12 以上で on。
- `binary_sensor.model_y_commute_days_90_percent`: 15 × 0.9 = 13.5 以上、つまり 14 以上で on。
- 2つの binary_sensor は、`sensor.model_y_commute_days` が数値のときだけ available にする。
- 上限の15日、割合、駐車場の一覧はテンプレートに直接書く。契約条件で決まり、UI から変える必要がないため（実装者の判断）。

`automations-alarm.yaml` に `automation.alarm_model_y_commute_days_warning` を追加する。2つの binary_sensor の `from: "off"` `to: "on"` をトリガーにし、`notify.tats_devices` に `⚠️ ALARM` を送る。メッセージには直近30日の通勤日数と、達したしきい値（12日か14日）を入れる。1つのオートメーションにまとめるのは実装者の判断。

ダッシュボード `dashboard-tesla` の `model-y` ビューの、距離警告のタイルの後ろに次のタイルを足す。距離警告と揃えるための実装者の提案で、利用者の依頼にはない。ダッシュボードは storage モードなので、デプロイ後に `ha_config_set_dashboard` で書き換える。

- `sensor.model_y_commute_days`（名前 "Commute Days"、12列1行）
- `binary_sensor.model_y_commute_days_80_percent` と `binary_sensor.model_y_commute_days_90_percent`（名前 "Commute Days 80%" と "Commute Days 90%"、それぞれ12列1行、`visibility` は state が `on` のとき）

`roles/homeassistant/tests/` に `model_y_insurance_distance.yml` と同じ形式のテストを追加し、上記の構成を検証する。

## 導入手順

デプロイ後、`ha_get_history` で直近30日の `sensor.model_y_geofence` の履歴を取り、通勤先の駐車場になった日付を集める。`ha_call_event` でイベント `model_y_commute_days_set` に日付のリストを渡し、`sensor.model_y_commute_days` の件数と `dates` 属性が集めた日付と一致することを確かめる。

## 実装者に任せる点

- テンプレートの具体的な書き方。`this` と `variables` の挙動、復元後の `this.attributes` は、実機の HA で `ha_eval_template` などを使って確かめる。
- アイコン、`unit_of_measurement`、`state_class`。
- 通知文の言い回し。
