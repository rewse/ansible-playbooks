# CloudFront 5xx 率から AWS Security Agent のペンテストを除く

## 目的

Zabbix のトリガー `CloudFront 5xx error rate is over 5% for 15 minutes`（alfa、High）は、AWS Security Agent の月次ペンテストが走るたびに発火する。2026-11-08 には 07:29 に発火した。原因は `monthly-grafana-rewse-jp` で、ペンテストが `grafana.rewse.jp` へ大量のリクエストを送り、TeslaMate の Grafana が不正な入力に 500 を返した。06:30 から 08:59 の Grafana の 5xx 1,352 件はすべてペンテストのクライアント `3.212.119.249` からで、origin の遅延は普段どおりだった。

ペンテストによる 5xx を率の計算から除き、実際の利用者が受けた 5xx だけでアラートを出す。

## ゴールと非ゴール

ゴール:

- ペンテストのリクエストを分子（5xx 数）と分母（リクエスト数）の両方から除いた 5xx 率でトリガーを判定する
- origin が止まって CloudFront 自身が 502 や 504 を返す障害は、今までどおり検知する

非ゴール:

- 4xx 率、WAF のメトリクスなど、5xx 以外の値からペンテストを除くこと
- ペンテストの日程や対象を変えること
- ペンテストのリクエストに CloudFront 自身が返した 5xx（タイムアウトなど）を除くこと。Apache に記録が残らないため数えられない

アンチゴール:

- 実際の障害を隠すこと。除外のためのデータが取れないときは、除かない値で判定する側に倒す
- 攻撃者が自分の 5xx を除外させられること。User-Agent はリクエスト側が自由に名乗れるため、識別には使わない

## 現状

- alfa の `roles/zabbix_aws/files/cloudfront_waf.sh` が 5 分ごとに CloudWatch の `AWS/CloudFront` から `Requests`（Sum）と `5xxErrorRate`（Average）などを 300 秒周期で取り、直近 10 分の最新のデータポイントを trapper アイテム `cloudfront.requests`、`cloudfront.error_rate.5xx` に送る。値の時刻は送信時刻になる
- トリガーはテンプレート `MyTemplate AWS CloudFront WAF` にあり、式は `min(cloudfront.error_rate.5xx,15m)>5 and count(cloudfront.error_rate.5xx,15m)>=3 and sum(cloudfront.requests,15m)>=30` である。テンプレートとトリガーはリポジトリではなく Zabbix 上で API から管理している。Zabbix は 7.4.16
- origin は `origin.rewse.jp` で、ルーターが fox に、フェイルオーバー時は hotel に転送する。どちらも `httpd` ロールの Apache が受ける
- ペンテストは秘密のヘッダー `X-Security-Agent-Pentest` を付けて来る。`roles/httpd/templates/security-agent-pentest.conf.j2` が値を照合して環境変数 `security_agent_pentest` を立て、`/var/log/apache2/security_agent_pentest.log` に `%{sec}t %a` を書く。fail2ban の `fail2ban-ignore-security-agent` がこのログの 1 列目と 2 列目を読む
- 2026-11-08 のペンテストでは、このログの 44,609 行と、UA が `securityagent` のアクセスログ 44,620 行がほぼ一致した。差の 11 行はヘッダーなしで来た事前確認のリクエストだった

## 検討した方法

1. Apache ログで差し引く（採用）: fox と hotel でペンテストのリクエスト数と 5xx 数を数え、CloudFront の値から引いた率で判定する。変更はこのリポジトリと Zabbix の設定で済み、origin 停止時の 502 や 504 も CloudFront 側の値に残る。CloudWatch と Apache の集計の枠をそろえる必要がある
2. CloudFront のアクセスログを使う: `~/git/cloudfront-waf` で standard logging v2 を CloudWatch Logs に出し、Logs Insights で UA やヘッダーを除いて集計する。CloudFront が返した 5xx まで正確に分けられるが、別リポジトリのデプロイとログ取り込みの料金がかかる
3. ペンテスト中はトリガーを抑える: 一番簡単だが、ペンテスト中の本当の障害を見逃す

ユーザーは 1 を選んだ。

## 設計

### ペンテストの識別

User-Agent ではなく、秘密のヘッダーで立つ `security_agent_pentest` で識別する（提案。理由はアンチゴールのとおり）。

`security_agent_pentest.log` の書式に応答コード `%>s` と、CloudFront 経由かどうかを示す `%{cloudfront_origin}e` を足し、`%{sec}t %a %>s %{cloudfront_origin}e` にする。`cloudfront_origin` は `roles/httpd/templates/cloudfront-origin.conf.j2` が origin ヘッダーの照合で立てる変数で、CloudFront 経由なら `1`、それ以外は `-` になる。スクリプトは 4 列目が `1` の行だけを数える。origin に直接来たペンテストのリクエストを CloudFront の値から引くと、引きすぎて利用者の 5xx が隠れるためである。列の足りない古い書式の行は数えない。fail2ban の ignore スクリプトは 1 列目と 2 列目しか読まないため影響しない。

このログには `roles/httpd/templates/security-agent-pentest.conf.j2` のサーバー全体の `CustomLog` のほか、`roles/teslamate/templates/grafana.rewse.jp.conf.j2` も書いている。vhost に `CustomLog` があるとサーバー側の設定を引き継がないためである。書式を `security-agent-pentest.conf.j2` で `LogFormat` の名前（`security_agent_pentest`）として定義し、両方の `CustomLog` がその名前を使うようにする（判断。書式を 1 か所にまとめ、ずれを防ぐ）。Apache は設定を読み終えてから名前を引くため、読み込み順は問わない。

### 5 分枠のそろえ方

CloudWatch と Apache の値を同じ 5 分枠で比べる。両方のスクリプトは、実行時刻を 300 秒で切り捨てた時刻から 600 秒前を枠の開始 B とし、[B, B+300) を集計する。枠が閉じてから 5 分以上たっているため、CloudWatch のデータも Apache の遅れて書かれる行もそろう。値は `zabbix_sender` のタイムスタンプ付き入力（`-T`）で B の時刻として送る。5 分ごとに 1 回実行するので、各枠は 1 回だけ送られる。

### fox と hotel（`httpd` ロール）

`security_agent` コンポーネントに Zabbix 用のスクリプトと UserParameter を足す（提案。ペンテストのログを持つコンポーネントに集める）。スクリプトは `security_agent_pentest.log` から枠 [B, B+300) の行を数え、trapper の `security_agent.requests` と `security_agent.errors.5xx` を送る。ペンテストがない枠でも 0 を送り、カウンターが動いていることを値の有無で分かるようにする。ログが読めないときは何も送らない。

### alfa（`zabbix_aws` ロール）

`cloudfront_waf.sh` に、同じ枠の値を送る新しいキー `cloudfront.bucket.requests` と `cloudfront.bucket.errors.5xx` を足す。5xx 数は `Requests` の Sum と `5xxErrorRate` の Average から `round(requests * rate / 100)` で出す。既存のキーと送り方は変えない。既存の `nodata` トリガーや週次レポートが使っているためである。

### Zabbix

テンプレート `MyTemplate AWS CloudFront WAF` に次を作る。

- 計算アイテム: ペンテストを除いたリクエスト数と 5xx 数、それを割った 5xx 率。過去 15 分の 3 枠を合計して出す。fox と hotel の値は両方を足す。まだ届いていない枠を数えないよう、時間シフトで十分過去の窓を見る
- トリガー: 既存の 5xx トリガーを置き換える。除外後の率が 5% を超え、除外後のリクエスト数が 30 以上のときに発火する。除外後のアイテムに 30 分値がないときは、今の式で判定する
- opdata に除外後の率とリクエスト数を出す

API で作ったら、AGENTS.md の規則どおり `zabbix-server` を再起動する。

## 制約

- 時間シフトのぶん、アラートは今より最大 15 分ほど遅れる。枠が閉じてから 5 分待つことと、全ホストの値が届くのを待つことによる
- 計算アイテムの式は、fox か hotel のどちらかの値がないときにアイテムごと unsupported にならないようにする。片方の Zabbix agent が止まっている状況こそ、障害を見逃したくない状況である
- AGENTS.md の Ansible の規約に従う。とくにコンポーネントのタグ、check mode で変更しないこと、2 回目の実行で `changed=0` になること、`command` と `shell` を避けること
- `security_agent_pentest.log` の `logrotate` 設定は変えない。ローテーション直後は枠の行が圧縮前の `security_agent_pentest.log.1` にあるため、スクリプトは現在のファイルと `.1` の両方を読む

## 実装する人に任せること

- スクリプトの言語（既存にならうなら bash）と細部
- 計算アイテムの式の書き方（`sum_foreach` を使うか、ホストを名指しするか）と時間シフトの値。制約を満たし、遅れが最小になるものを選ぶ
- テストの書き方。既存の `tests/test_zabbix_agent.py` のように、フィクスチャのログでスクリプトを動かして数え方を確かめるテストを含める
- 差し引いた 5xx 数やリクエスト数が負になったときは 0 で止める（判断）
- fox と hotel の trapper アイテムを置くテンプレート（既存の Apache 用テンプレートに足すか、新しく作るか）
- agent の実行時刻のずれで同じ枠を 2 回送ったり、1 回も送らなかったりしたときの扱い。2 回送っても率が大きくずれない式を選ぶ

## 検証

- `tests/` のテストと pre-commit を通す
- `home-primary.yml` と `home-secondary.yml` を `--tags httpd_security_agent` で、`home-primary.yml` を `--tags teslamate` で、`cloud-workstation.yml` を `--tags zabbix_aws_cloudfront_waf` で check のあと適用する
- `zabbix_get` で新しい UserParameter を呼び、Zabbix 上で新しいアイテムに枠の時刻つきの値が入ることを確かめる
- 2026-11-08 07:10 から 07:25 の枠について、CloudWatch と Apache ログから除外後の率を手で計算し、5% を下回ることを確かめる
