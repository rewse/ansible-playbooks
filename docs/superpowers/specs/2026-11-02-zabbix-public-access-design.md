# zabbix.rewse.jp の IP 制限撤廃 設計

## 目的

Zabbix を `https://zabbix.rewse.jp/zabbix/` で、家、会社、VPN 以外からも使えるようにする。主な利用者は iPhone の IntelliTrend Mobile で、5G 回線から Zabbix API を呼んで監視状況を見る。接続元の IP で絞る代わりに、`nas.rewse.jp` と同じく、ログイン、fail2ban、WAF のレート制限、月次 pentest で守る。API はこれに加えて、読み取りしかできないユーザーで使う。

## 現状

- Zabbix 7.4 の画面は、公式パッケージ `zabbix-apache-conf` が置く `/etc/apache2/conf-available/zabbix.conf` の `Alias /zabbix /usr/share/zabbix/ui` で配信している。`frontend.yml` は `a2enconf zabbix` で有効にするだけで、このファイルは Ansible の管理外である。Alias はサーバー全体に効くため、`zabbix.rewse.jp` 専用の vhost はなく、`zabbix.rewse.jp`、`rewse.jp`、`www.rewse.jp` はどれもデフォルト vhost の `/zabbix` に届く
- `roles/zabbix_server/templates/zabbix-api.conf.j2` が、サーバー全体の `<Location "/zabbix">` を loopback、家、会社に絞り、続く `<Location "/zabbix/api_jsonrpc.php">` を loopback と家だけに絞っている
- IntelliTrend Mobile は画面ではなく `/zabbix/api_jsonrpc.php` を呼ぶ。fox の `access.log` では、家の IPv6 からの `POST` は 200、5G の IPv6 からの `OPTIONS` は 403 になっている。アプリは `Admin` でログインしている。ログにあるアプリの呼び出しは、多いときで 10 分に 15 回である
- fox 上の zabbix-mcp-server は API を `https://rewse.jp/zabbix/` で呼ぶ。この URL は 1Password の項目に入っている
- fail2ban の `zabbix-web` jail は、`access.log`（combined 形式）の `POST /zabbix/index.php` と `POST /zabbix/index_mfa.php` への 200 を失敗として数える。パスワードと MFA の確認コードの両方を対象にしている。API はログインに失敗しても 200 を返し、エラーは本文に入るので、fail2ban はステータスから API の失敗を見分けられない
- Zabbix はアカウントごとに、5 回失敗すると 30 秒ロックする
- `zabbix.rewse.jp` はすでに CloudFront の `Aliases` にあり、WAF の `AWSManagedRulesPHPRuleSet` を通る。`RateLimitLogin` の対象は `/auth/`、`/login`、`/api/login` だけで、Zabbix のログインも API も入っていない
- security-agent には `zabbix.rewse.jp` の TargetDomain も pentest もない。`HomeTargetDomainApex` のコメントは、`zabbix.rewse.jp` もデフォルト vhost に来ると説明している
- `nas.rewse.jp` は `roles/filebrowser` が専用 vhost（`nas.rewse.jp.conf.j2`）を持ち、`Require ip` はない。fail2ban は `other_vhosts_access.log`（vhost_combined 形式）をホスト名で絞って読む。security-agent の月次 pentest は匿名で、毎月 16 日に動く
- Zabbix のユーザー、ユーザーグループ、ユーザーロールは Ansible で管理していない

## ゴール

- 5G 回線の IntelliTrend Mobile から `https://zabbix.rewse.jp/zabbix/` の API を使って監視状況を見られる
- `https://zabbix.rewse.jp/zabbix/` の画面に、どこからでも MFA 付きでログインできる
- アプリは読み取りしかできないユーザーで API を使い、`Admin` は画面からだけ使う
- `rewse.jp/zabbix` など、ほかのホスト名の `/zabbix` は、画面も API も今の IP 制限のまま残る
- 画面のログインと API への総当たりを、fail2ban、WAF のレート制限、Zabbix のアカウントロックが止める
- `zabbix.rewse.jp` に月次 pentest がかかる

## 範囲外

- Zabbix を `/zabbix` 以外のパス（ルートなど）で配信すること。公式の想定に合わせて `/zabbix` のままにする
- zabbix-mcp-server と 1Password の MCP 用 API URL の変更
- `zabbix-mcp.rewse.jp` の公開範囲
- Zabbix のユーザー、グループ、ロールを Ansible で管理すること
- pentest に読み取りユーザーでログインさせること
- WAF の `BlockManagedRules` の有効化

## 制約

- 公式の `zabbix.conf` は書き換えない。パッケージの更新で上書きされる
- Apache は `<VirtualHost>` の中の `<Location>` を、サーバー全体の `<Location>` より後にマージする。同じ種類のセクションはファイルに書いた順に適用される
- 新しい vhost のログは `other_vhosts_access.log` に vhost_combined 形式で書かれ、クライアントのアドレスは 2 番目のフィールドになる
- `cloudfront-origin.conf.j2` は、CloudFront の秘密のヘッダーがないリクエストのうち、loopback、家、VPN 以外から来たものを 403 にする。`mod_remoteip` が CloudFront 経由の接続元を復元するため、fail2ban と `Require ip` は本当の接続元を見る
- API の `user.login` には MFA がかからないとみている。計画の段階で Zabbix 7.4 の文書で確かめる。かからないなら、API はパスワードだけで入れる

## 方式

| 方式 | 内容 | 判断 |
|---|---|---|
| A | `zabbix.rewse.jp` 専用 vhost を作り、その中だけ `/zabbix` を全員に開く。URL は `/zabbix` のまま | 採用 |
| B | 専用 vhost を作り、Zabbix をルートで配信する | 不採用。公式は `/zabbix` での配信を想定している。MCP の URL、fail2ban、WAF のパスも書き換えることになる |
| C | 既存の conf に `<If "%{HTTP_HOST} == 'zabbix.rewse.jp'">` を書いて制限を外す | 不採用。公開範囲が vhost ではなく条件式で決まり、AGENTS.md のサブドメインの決まり（サービスごとに `<name>.rewse.jp.conf.j2` を置く）から外れる |

一度は B を選んだが、`zabbix.conf` が公式パッケージの設定だとわかったところで、公式どおりの A に戻した。

最初は画面だけを開き、API は家だけに残す案だった。アプリが API を使っているとわかったので、`zabbix.rewse.jp` では API も開き、読み取りユーザーとレート制限で補う形にした。

## 設計

### ansible-playbooks

`roles/zabbix_server` に `apache` コンポーネントを追加する。

- `vars/main.yml` に `zabbix_server_hostname: zabbix.rewse.jp` を追加する
- `templates/zabbix.rewse.jp.conf.j2` を追加する。`<VirtualHost *:443>` に `ServerName {{ zabbix_server_hostname }}` を置き、次を書く
  - `/` を `/zabbix/` にリダイレクトする（`RedirectMatch ^/$ /zabbix/`）
  - `<Location "/zabbix">` を `Require all granted` にする。サーバー全体の `<Location "/zabbix/api_jsonrpc.php">` はこれより前にマージされるので、この vhost では API も開く
  - 証明書の 3 行は `nas.rewse.jp.conf.j2` と同じにする
- `tasks/apache.yml` を追加する。`roles/filebrowser/tasks/apache.yml` と同じく、テンプレートを `/etc/apache2/sites-available/{{ zabbix_server_hostname }}.conf` に置き、`a2ensite` で有効にする。`tasks/main.yml` で `zabbix_server_apache` タグを付けて読み込む
- `zabbix-api.conf.j2` の `Require ip` はそのまま残し、コメントを直す。この制限は `zabbix.rewse.jp` 以外のホスト名の `/zabbix` に効く。`zabbix.rewse.jp` は専用 vhost で画面も API も開いており、API は読み取りユーザーと WAF のレート制限で守る、と書く。「API は LAN の外に要らない」という今の説明は消す
- fail2ban の `zabbix-web` を、新しい vhost のログも読めるように直す
  - フィルタを `files/fail2ban-filter.conf` から `templates/fail2ban-filter.conf.j2` に移し、`failregex` に `^{{ zabbix_server_hostname | regex_escape }}:\d+ <HOST> ...` の行を足す。デフォルト vhost の行は残す。家と会社からは今も `rewse.jp/zabbix` に届くためである
  - jail の `logpath` に `/var/log/apache2/other_vhosts_access.log` を足す
  - `tasks/fail2ban.yml` のフィルタのタスクを `copy` から `template` に変える
- テストを更新する
  - `tests/test_privilege_hardening.py` の `ZabbixFrontendTest` はそのまま通るはずである。新しい vhost について、`/zabbix` が `Require all granted` であること、テンプレートから配置されることを確かめるテストを足す
  - 新しい vhost のログ行を fail2ban のフィルタが拾い、デフォルト vhost のログ行も引き続き拾うことを確かめる
- AGENTS.md の Zabbix 節にある「`zabbix_get` は `zabbix.rewse.jp` から」という記述は、エージェントの `Server=` の話なので変えない

### Zabbix の読み取りユーザー

API で作る。Ansible では管理しないので、作る手順は実装計画に書く。

- ユーザーロール: 種類は User とする。API のアクセスを有効にし、API メソッドは許可リストで `*.get`、`user.login`、`user.logout` だけを許す。アプリが画面を開くことはないので、UI 要素とアクションはできるだけ閉じる
- ユーザーグループ: 全ホストグループへの読み取り権限だけを与える。画面へのログインを無効にしても API のログインが通るなら無効にする。通るかどうかは実装時に確かめる
- ユーザー: パスワードを生成して 1Password に新しい項目として置く。項目名は Common Standards の命名に従う
- IntelliTrend Mobile の接続先を `https://zabbix.rewse.jp/zabbix/`、ユーザーをこの読み取りユーザーに切り替える。アプリの設定はユーザーが手で行う
- 切り替えたあと、アプリから監視状況が見られること、`Admin` での API ログインがアプリに残っていないことを確かめる

### cloudfront-waf

- `infra/template.yaml` の `RateLimitLogin` の `OrStatement` に、`STARTS_WITH /zabbix/index` の `ByteMatchStatement` を足す。`index.php` と `index_mfa.php` の両方に一致する。上のコメントに Zabbix を足す
- `RateLimitZabbixApi` を新しく足す。`/zabbix/api_jsonrpc.php` で始まるパスを対象に、IP ごとに 5 分あたり 300 リクエストを超えたらブロックする。上限は、アプリの呼び出しが多いときで 10 分に 15 回だったことから、余裕を持たせた値である。`RateLimitLogin` と上限が違うので別のルールにする。優先度は `RateLimitLogin` と `RateLimitAll` の近くに置き、既存の優先度の付け直しが要るなら実装者が決める
- `tests/test_template.py` の `RateLimitLogin` の期待するパスの集合、ルール名の一覧、新しいルールのテストを更新する。`README.md` のルールの表も更新する
- `AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` で反映する。名前は増えないので、`switch-dns.sh` と `SUBDOMAINS` は変えない

### security-agent

- `infra/template.yaml` に `HomeTargetDomainZabbix`（`zabbix.rewse.jp`、`DNS_TXT`）を足し、ほかのドメインと同じく Agent Space に結び付ける
- `SitePentestZabbix`（Title `monthly-zabbix-rewse-jp`）を足す。中身は `SitePentestNas` と同じで、匿名、同じ `ExcludeRiskTypes`、`X-Security-Agent-Pentest` ヘッダーを付ける。エンドポイントは `https://zabbix.rewse.jp/zabbix/` とする
- `SiteScheduleZabbix` を足し、毎月 13 日の 21:15 UTC に動かす。サイトごとの pentest は 1、4、7、10、16、19、22、25、28 日に 1 つずつ動いており、13 日はその並びの空きである
- `targets.toml` に `monthly-zabbix-rewse-jp` を足し、指摘は `ansible-playbooks` に送る
- `tests/test_infra.py` の `HOME_SITES` と `SCHEDULE_DAYS` を更新する
- `HomeTargetDomainApex` のコメントから `zabbix.rewse.jp` を外す
- TXT レコードを作ってドメインを検証してから、`security-agent-deploy` プロファイルで反映する。手順は security-agent の `docs/setup.md` に従う

## 公開前の確認

インターネットに開く前に、Zabbix の設定を API で読んで次を確かめる。満たしていなければ、開く前に直す。

- Guest ユーザーが無効で、Guests グループの画面アクセスも無効である
- 画面にログインできるユーザーは全員 MFA が必須である
- `Admin` のパスワードが初期値ではない
- 読み取りユーザーで書き込み系の API（たとえば `host.update`）を呼ぶと拒否される

## 反映の順番

1. cloudfront-waf の `RateLimitLogin` と `RateLimitZabbixApi` を反映する。開く前にレート制限を効かせるためである
2. Zabbix に読み取りユーザーを作り、公開前の確認をする
3. ansible-playbooks で `zabbix_server` を fox に反映する（`zabbix_server_apache` と `zabbix_server_fail2ban`）
4. 5G 回線から次を確かめる。`https://zabbix.rewse.jp/zabbix/` の画面と API が使えること、`https://rewse.jp/zabbix/` が 403 になること。fail2ban の `zabbix-web` が両方のログを読んでいることを `fail2ban-client get zabbix-web logpath` で確かめる
5. IntelliTrend Mobile を読み取りユーザーに切り替える
6. security-agent のドメインを検証し、pentest とスケジュールを反映する

## 実装者に任せること

- テストを既存のどのファイルに足すか、新しいファイルにするか
- vhost とフィルタのコメントの文面
- `RedirectMatch` か `RewriteRule` か
- 読み取りユーザー、グループ、ロールの名前
- WAF のルールの優先度の番号
