# Muse から Sakura のメールを使う MCP サーバー 設計

## 目的

Meta Muse から Sakura のメール（rewse.jp、MX `rewse.sakura.ne.jp`）を読み、迷惑メールを判定して移動、削除できるようにする。家族もそれぞれの Muse から自分のメールボックスに同じことができるようにする。

Muse の Secure Credentials Store は HTTPS のリクエストにしか資格情報を差し込まない。Sentinel が外向きの通信の境界で代わりの値を本物に置き換える仕組みで、IMAP のログインには使えない。そのため今は Mac を経由しており、Mac がスリープしている間は Muse がメールに届かない。常時動いている fox に HTTPS の MCP サーバーを置き、Muse からはベアラートークンだけで使えるようにする。

## ゴール

- Mac の状態に関係なく、Muse から `https://mail-mcp.rewse.jp/mcp` でメールの一覧、検索、読み取り、フォルダー移動、ゴミ箱への移動、ゴミ箱からの完全削除ができる
- 家族一人ずつに別のトークンを発行し、各トークンでは本人のメールボックスにしか触れない
- トークンを持っていても、メールの送信と下書きの作成はできない
- トークンの総当たりを fail2ban が止める
- 誰がいつ何をしたかが監査ログに残る

## 範囲外

- メールの送信、返信、下書き。Muse が迷惑メールの文面にだまされても、外にメールを出させない
- 新着メールの webhook（docker-mailbox の `watch`）
- 迷惑メールの判定ロジック。判定は Muse が行い、サーバーは道具を渡すだけとする
- OAuth による認可。Muse はベアラートークンをヘッダーに差し込めるので要らない
- Mac 経由の今の仕組みの撤去。新しい経路で動くのを確かめてから利用者が判断する
- WAF の `BlockManagedRules` の有効化

## 制約

- Muse の接続元は Meta のクラウドで、アドレスがわからない。zabbix-mcp のように `Require ip` で絞れず、インターネット全体に公開することになる
- Muse のアプリには MCP サーバーの URL を登録する画面がない。チャットで「この MCP サーバーにつなぐカスタムコネクタを作って」と頼み、トークンは Muse が開く入力欄から Secure Credentials Store に入れる。Meta はこの使い方を公式には説明していないが、Muse から TickTick の MCP は使えている
- 家族全員の Sakura のパスワードは利用者が管理しており、サーバーにまとめて置いてよい
- CloudFront のオリジン読み取りタイムアウトは 60 秒で、それより長いリクエストは失敗する
- docker-mailbox はスター 7、v0.8.0（2026-10-27）の若いプロジェクトで、更新が速い。ライセンスは WTFPL

## 方式

| 方式 | 内容 | 判断 |
|---|---|---|
| A | psyb0t/docker-mailbox を fox のコンテナで動かし、Apache の vhost と CloudFront で公開する。トークンごとに権限とメールボックスを絞る | 採用 |
| B | n24q02m/better-email-mcp を同じ形で公開し、OAuth 2.1 で認可する | 不採用。ユーザーごとに操作の権限を絞れず、Muse がだまされたときに送信までできてしまう。OAuth の認可サーバーも抱えることになる |
| C | IMAP の MCP サーバーを自作する | 不採用。必要な機能は A にそろっている |

A は、トークンごとにできる操作（`read`、`organize`、`delete` など）と触れるメールボックスを設定ファイルで決められ、REST と MCP の両方に同じ制限がかかる。若いプロジェクトであることは、`aged_release` の待機期間とイメージのダイジェスト固定、更新前の CHANGELOG の確認で補う。

## 構成

```mermaid
flowchart LR
  muse["Muse<br/>（家族それぞれ）"] -->|"mail-mcp.rewse.jp<br/>Authorization: Bearer"| cf["CloudFront<br/>+ AWS WAF"]
  cf -->|"origin.rewse.jp:443<br/>X-Origin-Verify"| apache["Apache on fox<br/>fail2ban"]
  home["家、VPN"] -->|"UniFi の DNS"| apache
  apache -->|"http://127.0.0.1:ポート"| mailboxd["mailboxd<br/>（コンテナ）"]
  mailboxd -->|"IMAPS 993"| sakura["Sakura のメール"]
```

### mailboxd ロール

新しいロール `mailboxd` を作り、fox の playbook に加える。名前は docker-mailbox のデーモン名に合わせた。`roles/filebrowser` を手本にし、コンポーネントは config、container、apache、fail2ban とする。

- container コンポーネント
  - イメージは `aged_release` の `oci:psyb0t/mailbox` で `^v\d+\.\d+\.\d+$` に一致するタグを選び、`tag@digest` で固定する。Docker Hub には amd64 と arm64 がある。`latest` と `sha-*` のタグは使わない
  - Compose プロジェクトは `/etc/compose/mailboxd/compose.yaml`。上流の `docker-compose.yml` の守り（`read_only`、`cap_drop: [ALL]`、`no-new-privileges`、tmpfs の `/tmp`、メモリと PID の上限、ヘルスチェック）を引き継ぐ。`watch` サービスは含めない
  - 待ち受けは `127.0.0.1` のみ。ポートは fox で空いているものを選ぶ
  - 状態の SQLite（監査ログ、チェックポイント）は `/srv/mailboxd` をバインドマウントして残す
- config コンポーネント
  - `config.yaml` に、メールボックスとトークンの定義を描画する。パスワードとトークンは `${VAR}` で参照し、値は `.env`（`env_file`）に描画する。`.env` は root だけが読める権限にし、Docker が root で読んでコンテナに渡す
  - メールボックスは家族一人に一つ。`imap` だけを定義し、`smtp` は定義しない。IMAP は `rewse.sakura.ne.jp:993`、`tls: ssl`
  - トークンは家族一人に一つ。`scopes: [read, organize, delete]`、`mailboxes` は本人のメールボックスだけにする。`draft`、`send`、`admin` は付けず、`"*"` も使わない。`delete` はゴミ箱からの完全削除だけを許す権限で、ゴミ箱への移動は `organize` に含まれる
  - トークンの文字列形式（すべての権限とすべてのメールボックスを許す）は使わない
  - `auth.trusted_authserv_id` は、Sakura が受信メールに付ける `Authentication-Results` の値にする。Muse が SPF、DKIM、DMARC の結果を迷惑メールの判定に使えるようにするため
- apache コンポーネント
  - `templates/mail-mcp.rewse.jp.conf.j2` を置き、zabbix-mcp の vhost と同じく `ProxyPreserveHost on` と `ProxyPass ... flushpackets=on` で `127.0.0.1` に流す。`Require ip` は付けない
  - 証明書は既存の `*.rewse.jp` を使う
- fail2ban コンポーネント
  - フィルタは `mail-mcp.rewse.jp` の vhost で `/mcp` に 401 が返った行に一致させる。`/health` と、もしあれば `/.well-known/` は対象外とする
  - ジェイルの形は filebrowser と zabbix-mcp に合わせ、`tests/test_fail2ban_apache.py` の一覧に加える
  - Muse の接続元は家族で共有している可能性がある。誤ったトークンで BAN されると家族全員が一時間使えなくなるが、許容する
- 1Password
  - 家族それぞれの Sakura のパスワードと、家族それぞれの MCP トークンを `ansible` vault に置き、コミットするのは Secret Reference だけにする。項目名は `System - Consumer` の規則に従う
  - トークンは `openssl rand -hex 32` で作る。トークンの値は、本人が Muse の入力欄に入れるために 1Password から渡す
- テスト
  - `tests/test_mailboxd.py` で、テンプレートを描画して確かめる。待ち受けがループバックだけであること、どのトークンも `send`、`draft`、`admin` を持たず、`mailboxes` が一つだけであること、`smtp` がないこと、`.env` の権限、vhost のプロキシ先、ジェイルの設定、フィルタが一致する行と一致しない行を対象にする

### 他のリポジトリと DNS

AGENTS.md の「Subdomains」の手順に従う。

- `~/git/cloudfront-waf`: `mail-mcp.rewse.jp` を CloudFront の別名と `SUBDOMAINS` に加え、テストと文書の名前の一覧と数を直してデプロイする。`AWS_PROFILE=cloudfront-waf-deploy` の作業は、利用者に会社の Mac で実行してもらう
- UniFi: `mail-mcp.rewse.jp` を `fox.rewse.jp` に向ける CNAME の DNS ポリシーを加える
- `~/git/security-agent`: インターネットから誰でも届く名前なので、毎月のペネトレーションテストに加え、対象ドメインを検証する
- `~/git/chezmoi`: クライアント設定に URL を書く場所はないので変更しない

### 更新

`update` タグで `aged_release` が新しいタグを選ぶ。v0 のうちは minor の更新でも設定の互換性が崩れることがあるので、新しいタグを入れる前に上流の CHANGELOG と移行ノート（`docs/operations.md`）を読む。

## 確かめること

- 家から `/health` が 200、トークンなしの `POST /mcp` が 401 を返す
- 家族一人のトークンで、ほかの家族のメールボックスを指定すると拒否される
- `send` 系の道具を呼ぶと拒否される
- CloudFront 経由で外から MCP の `initialize` と道具の一覧が通る
- Muse にカスタムコネクタを作らせ、自分のメールボックスで一覧、移動、ゴミ箱への移動、完全削除ができる。そのあと家族の Muse でも同じことを確かめる
- WAF のログで、Muse の通信が管理ルールに誤検知されていないことを見る

## 残るリスク

- Muse がベアラートークンの MCP サーバーにつなげない場合。TickTick の MCP は使えているが、認証方式が OAuth なら条件が違う。つながらなければ、Muse に REST API（同じポートの HTTP API）向けのコネクタを作らせる。それも駄目なら、方式 B の OAuth を考え直す
- docker-mailbox の開発が止まる、または互換性のない変更が続く場合。イメージを固定しているので急に壊れはしない。自作か別の実装への乗り換えを、その時点で判断する
- 家族全員の Sakura のパスワードが fox の一か所に集まる。fox が侵害されたときの影響は大きい

## 実装者に任せること

- 待ち受けのポート番号
- 1Password の項目の作り方と項目 ID
- 家族のメールボックスとトークンを並べる変数の形
- `/srv/mailboxd` をバックアップの対象に加えるかどうか
- `limits` と `log_level` の値
