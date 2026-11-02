# Roomba Combo 最終掃除日時の記録

## 目的

`input_datetime.roomba_combo_next` は「次に自動スタートしてよい日時」を保存している。Model Y の最終フルチャージ日時と同じく、最後に掃除した日時を記録し、自動スタートの判定をその日時ベースに変える。next は不要になるので削除する(利用者の決定)。

## ゴールと非ゴール

- ゴール: 最後に掃除を始めた日時を Home Assistant 上で確認できる
- ゴール: 自動スタートは、最後の掃除から 2 日経っていることを条件にする
- 非ゴール: 自動スタートのほかの条件(全員不在 10 分、ドック、バッテリー 50% 以上)を変えること
- 非ゴール: 次に動ける日時を別のエンティティで表示すること

## アプローチ

- A. `input_datetime` に最終掃除日時だけを保存し、next を削除する。Model Y と同じ作りで、保存する値が 1 つになる(採用)
- B. A に加えて、next をテンプレートの timestamp センサーで計算して表示する。ダッシュボードで次の日時を見られるが、エンティティが増える

利用者は A を選んだ。

## 決めたこと

- `input_datetimes.yaml` の `roomba_combo_next` を削除し、`roomba_combo_last_cleaning`(名前 "Roomba Combo Last Cleaning"、日付と時刻あり)を追加する
- `automations-others.yaml` の `automation.update_roomba_combo_next_date` を `automation.record_roomba_combo_last_cleaning`(alias "Record Roomba Combo Last Cleaning")に置き換える。トリガーの「`cleaning` が 30 分続いた」は維持し、30 分未満で止まった掃除は数えない
- 記録する日時は、30 分後の `now()` ではなく `cleaning` になった時刻(`trigger.to_state.last_changed`)とする
- `automation.start_roomba_combo` の条件を「`roomba_combo_last_cleaning` から 2 日以上経った」に変える
- デプロイ後、前回の掃除開始時刻(2026-11-01 17:00 ごろ、履歴で正確な時刻を確認する)を初期値として入れる
- ダッシュボードの参照を書き換える(storage モードなので ha-mcp で行う)
  - Overview(`lovelace`)の `input_datetime.roomba_combo_next` のタイル → `input_datetime.roomba_combo_last_cleaning`
  - `dashboard-internal` の "Update Next" タイル → `automation.record_roomba_combo_last_cleaning`、名前 "Record Last"、トレースの URL も新しい ID にする
  - `dashboard-internal` の `input_datetime.roomba_combo_next` のタイル → `input_datetime.roomba_combo_last_cleaning`
- 旧オートメーションのエンティティはレジストリに残るので削除する

## 実装者の判断に任せること(Kiro の判断)

- 判定は `now().timestamp() - state_attr('input_datetime.roomba_combo_last_cleaning', 'timestamp') >= 2 * 86400` とする。以前は掃除開始の 30 分後から 2 日を数えていたので、自動スタートできる時刻が 30 分早まる
- 初期値を入れるまでの間、新しい `input_datetime` は今日の 0 時になる。2 日未満なので自動スタートは起きず、安全側に倒れる
- `input_datetimes.yaml` と `automations-*.yaml` はどちらも再起動なしで反映できるので、配備は 1 回で行い、`input_datetime.reload`、`automation.reload` の順に呼ぶ
- Roomba のテストがまだ無いので、`roles/homeassistant/tests/roomba_combo.yml` を Model Y のテストと同じ形で追加する
