# fox の NVMe 通知を異常な頻度のときだけに絞る

## 目的

Zabbix のトリガー `NVMe I/O errors in syslog on fox`（triggerid 17024、High）は、syslog に NVMe のエラーが 1 行出るだけで発報する。2026-08-15 からの約 12 週間で約 30 回発報し、通知を見ても無視するようになった。何度調査しても実害はなく、リンク断はカーネルのリセットで自力復帰している。通知は、普段より異常に多いときと、ドライブ自体が劣化したときだけに絞る。

## 現状

- 発報の大半は起動中や稼働中の `nvme nvme0: controller is down; will reset` と、それに続く 16 行前後の `I/O error, dev nvme0n1`。1 回のリンク断で 1 回発報する。
- トリガー 17024 の発報回数は週 1〜3 回が普通で、最大は 9/24〜9/30 の 12 回。トリガーは `find(...,30m)` なので、30 分以内に続いたリセットは 1 回の発報にまとまる。Syslog の history は 1w しかなく、過去のリセット行数は数え直せない。
- `nvme smart-log /dev/nvme0` は critical_warning 0、media_errors 0、num_err_log_entries 0、available_spare 100%、percentage_used 7%。リンク断はドライブのエラーログに残らない。
- トリガーと Syslog アイテム（`log[/var/log/syslog,,UTF-8]`、itemid 29517、history 1w）は Zabbix API で作ってあり、このリポジトリでは管理していない。

## ゴール

- リンク断の回数を参考値として記録し、グラフで推移を見られるようにする。
- 回数が普段より異常に多いときだけ通知する。
- SMART でドライブ自体の劣化を検知したら通知する。

## 非ゴール

- `/` が read-only になる崩壊そのものの検知。Zabbix サーバーも fox で動いているため、fox の外から見張る仕組みが要る。今回は扱わない。
- リンク断の原因調査や修理。

## アプローチ

検討した案は 2 つ。

- A: ログは参考値だけにして、通知は SMART の劣化に絞る。最も静かになるが、リンク断が増えても気づけない。
- B: A に加えて、リンク断の回数が異常に多いときだけ通知する。ユーザーは B を選んだ。リンク断はたまに起きる程度なら問題ないが、急増はケーブルや HAT の悪化を示すため。

## 設計

### リンク断の回数

- fox に active のログ件数アイテム `log.count[/var/log/syslog,"nvme.*(controller is down|Unable to change power state)",UTF-8,,skip]` を作る。間隔 5m、history 90d、trends 365d。リセット 1 回につき 1 行だけ数え、後続の `I/O error` 行は数えない。`skip` で作成時点の既存行は数えない。
- トリガー `NVMe link resets are unusually frequent on fox`：`sum(<上記アイテム>,7d)>=5`、重要度 Warning。普段の週 1〜3 回では発報せず、9/24〜9/30 の週なら発報する。式が偽に戻れば自動で解決する。しきい値 5 は発報回数から見積もった初期値で、行数の実績が数週間たまったら見直す（実装側の判断）。
- 既存のトリガー 17024 は削除する。Syslog アイテム 29517 はほかのトリガーやログ閲覧に使うので残す。

### SMART

- `roles/zabbix_agent/files/raspberrypi.conf` に、`nvme smart-log -o json` から値を取り出す UserParameter を追加する。Raspberry Pi の agent はすでに root で動いているので、sudo の設定は要らない。NVMe を読めないときは何も出力しない。
- fox に次のアイテムとトリガーを作る。

| 値 | トリガー | 重要度 |
|---|---|---|
| critical_warning | `<>0` | High |
| media_errors | 前回値から増えた | High |
| available_spare | available_spare_threshold 以下 | High |
| percentage_used | `>=90` | Warning |
| temperature | なし（参考値） | - |

- media_errors のトリガーは `change()>0` で発報し、自動では解決させない（OK イベント生成を「なし」、手動クローズを許可）。そうしないと、次の取得で値が変わらないだけで解決になり、劣化の記録が問題一覧から消えてしまう（実装側の判断）。
- Zabbix のアイテムとトリガーは、既存の 17024 と同じく API で作る。このリポジトリには Zabbix の設定をコードで管理する仕組みがなく、今回は作らない（実装側の判断）。

## ビルダーに任せること

- UserParameter のキー名と JSON の取り出し方。
- Zabbix の通知アクションが Warning を通知対象に含むかの確認。含まなければ報告する。
- hotel など fox 以外の NVMe ホストにアイテムを作るかどうか。UserParameter は NVMe のないホストでは何も出力しない。
