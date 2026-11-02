# zabbix.rewse.jp の IP 制限撤廃 設計

## 目的

Zabbix の画面を `https://zabbix.rewse.jp/zabbix/` で、家、会社、VPN 以外からも使えるようにする。接続元の IP で絞る代わりに、`nas.rewse.jp` と同じく、ログイン、fail2ban、WAF のレート制限、月次 pentest で守る。

## 現状

- Zabbix 7.4 の画面は、公式パッケージ `zabbix-apache-conf` が置く `/etc/apache2/conf-available/zabbix.conf` の `Alias /zabbix /usr/share/zabbix/ui` で配信している。`frontend.yml` は `a2enconf zabbix` で有効にするだけで、このファイルは Ansible の管理外である。Alias はサーバー全体に効くため、`zabbix.rewse.jp` 専用の vhost はなく、`zabbix.rewse.jp`、`rewse.jp`、`www.rewse.jp` はどれもデフォルト vhost の `/zabbix` に届く
- `roles/zabbix_server/templates/zabbix-api.conf.j2` が、サーバー全体の `<Location "/zabbix">` を loopback、家、会社に絞り、続く `<Location "/zabbix/api_jsonrpc.php">` を loopback と家だけに絞っている
- fox 上の zabbix-mcp-server は API を `https://rewse.jp/zabbix/` で呼ぶ。この URL は 1Password の項目に入っている
- fail2ban の `zabbix-web` jail は、`access.log`（combined 形式）の `POST /zabbix/index.php` と `POST /zabbix/index_mfa.php` への 200 を失敗として数える。パスワードと MFA の確認コードの両方を対象にしている
- `zabbix.rewse.jp` はすでに CloudFront の `Aliases` にあり、WAF の `AWSManagedRulesPHPRuleSet` を通る。`RateLimitLogin` の対象は `/auth/`、`/login`、`/api/login` だけで、Zabbix のログインは入っていない
- security-agent には `zabbix.rewse.jp` の TargetDomain も pentest もない。`HomeTargetDomainApex` のコメントは、`zabbix.rewse.jp` もデフォルト vhost に来ると説明している
- `nas.rewse.jp` は `roles/filebrowser` が専用 vhost（`nas.rewse.jp.conf.j2`）を持ち、`Require ip` はない。fail2ban は `other_vhosts_access.log`（vhost_combined 形式）をホスト名で絞って読む。security-agent の月次 pentest は匿名で、毎月 16 日に動く

## ゴール

- `https://zabbix.rewse.jp/zabbix/` の画面に、どこからでもログインできる
- `rewse.jp/zabbix` など、ほかのホスト名の `/zabbix` は今の IP 制限のまま残る
- API（`api_jsonrpc.php`）は、どのホスト名でも loopback と家からしか使えない
- インターネットからのログインの総当たりを、fail2ban と WAF のレート制限が止める
- `zabbix.rewse.jp` に月次 pentest がかかる

## 範囲外

- Zabbix を `/zabbix` 以外のパス（ルートなど）で配信すること。公式の想定に合わせて `/zabbix` のままにする
- zabbix-mcp-server と 1Password の API URL の変更
- `zabbix-mcp.rewse.jp` の公開範囲
- Zabbix の読み取り専用アカウントを作って、pentest にログインさせること
- WAF の `BlockManagedRules` の有効化

## 制約

- 公式の `zabbix.conf` は書き換えない。パッケージの更新で上書きされる
- Apache は `<VirtualHost>` の中の `<Location>` を、サーバー全体の `<Location>` より後にマージする。同じ種類のセクションはファイルに書いた順に適用されるので、API のブロックは画面のブロックより後に置く
- 新しい vhost のログは `other_vhosts_access.log` に vhost_combined 形式で書かれ、クライアントのアドレスは 2 番目のフィールドになる
- `cloudfront-origin.conf.j2` は、CloudFront の秘密のヘッダーがないリクエストのうち、loopback、家、VPN 以外から来たものを 403 にする。`mod_remoteip` が CloudFront 経由の接続元を復元するため、fail2ban と `Require ip` は本当の接続元を見る

## 方式

| 方式 | 内容 | 判断 |
|---|---|---|
| A | `zabbix.rewse.jp` 専用 vhost を作り、その中だけ `/zabbix` を全員に開く。URL は `/zabbix` のまま | 採用 |
| B | 専用 vhost を作り、Zabbix をルートで配信する | 不採用。公式は `/zabbix` での配信を想定している。MCP の URL、fail2ban、WAF のパスも書き換えることになる |
| C | 既存の conf に `<If "%{HTTP_HOST} == 'zabbix.rewse.jp'">` を書いて制限を外す | 不採用。公開範囲が vhost ではなく条件式で決まり、AGENTS.md のサブドメインの決まり（サービスごとに `<name>.rewse.jp.conf.j2` を置く）から外れる |

一度は B を選んだが、`zabbix.conf` が公式パッケージの設定だとわかったところで、公式どおりの A に戻した。

## 設計

### ansible-playbooks

`roles/zabbix_server` に `apache` コンポーネントを追加する。

- `vars/main.yml` に `zabbix_server_hostname: zabbix.rewse.jp` を追加する
- `templates/zabbix.rewse.jp.conf.j2` を追加する。`<VirtualHost *:443>` に `ServerName {{ zabbix_server_hostname }}` を置き、次を書く
  - `/` を `/zabbix/` にリダイレクトする（`RedirectMatch ^/$ /zabbix/`）
  - `<Location "/zabbix">` を `Require all granted` にする
  - その後に `<Location "/zabbix/api_jsonrpc.php">` を置き、`zabbix-api.conf.j2` と同じ loopback と家のアドレスだけを許可する
  - 証明書の 3 行は `nas.rewse.jp.conf.j2` と同じにする
- `tasks/apache.yml` を追加する。`roles/filebrowser/tasks/apache.yml` と同じく、テンプレートを `/etc/apache2/sites-available/{{ zabbix_server_hostname }}.conf` に置き、`a2ensite` で有効にする。`tasks/main.yml` で `zabbix_server_apache` タグを付けて読み込む
- `zabbix-api.conf.j2` の `Require ip` はそのまま残し、コメントを直す。この制限は `zabbix.rewse.jp` 以外のホスト名の `/zabbix` に効き、`zabbix.rewse.jp` は専用 vhost で開いている、と書く
- fail2ban の `zabbix-web` を、新しい vhost のログも読めるように直す
  - フィルタを `files/fail2ban-filter.conf` から `templates/fail2ban-filter.conf.j2` に移し、`failregex` に `^{{ zabbix_server_hostname | regex_escape }}:\d+ <HOST> ...` の行を足す。デフォルト vhost の行は残す。家と会社からは今も `rewse.jp/zabbix` に届くためである
  - jail の `logpath` に `/var/log/apache2/other_vhosts_access.log` を足す
  - `tasks/fail2ban.yml` のフィルタのタスクを `copy` から `template` に変える
- テストを更新する
  - `tests/test_privilege_hardening.py` の `ZabbixFrontendTest` はそのまま通るはずである。新しい vhost について、`/zabbix` が `Require all granted` であること、API のブロックが後にあって loopback と家だけを許すこと、テンプレートから配置されることを確かめるテストを足す
  - 新しい vhost のログ行を fail2ban のフィルタが拾い、デフォルト vhost のログ行も引き続き拾うことを確かめる
- AGENTS.md の Zabbix 節にある「`zabbix_get` は `zabbix.rewse.jp` から」という記述は、エージェントの `Server=` の話なので変えない

### cloudfront-waf

- `infra/template.yaml` の `RateLimitLogin` の `OrStatement` に、`STARTS_WITH /zabbix/index` の `ByteMatchStatement` を足す。`index.php` と `index_mfa.php` の両方に一致する。上のコメントに Zabbix を足す
- `tests/test_template.py` の期待するパスの集合と、`README.md` の `RateLimitLogin` の行を更新する
- `AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` で反映する。名前は増えないので、`switch-dns.sh` と `SUBDOMAINS` は変えない

### security-agent

- `infra/template.yaml` に `HomeTargetDomainZabbix`（`zabbix.rewse.jp`、`DNS_TXT`）を足し、ほかのドメインと同じく Agent Space に結び付ける
- `SitePentestZabbix`（Title `monthly-zabbix-rewse-jp`）を足す。`SitePentestNas` と同じ形で、匿名、同じ `ExcludeRiskTypes`、`X-Security-Agent-Pentest` ヘッダーを付ける。エンドポイントは `https://zabbix.rewse.jp/zabbix/` とする
- `SiteScheduleZabbix` を足し、毎月 13 日の 21:15 UTC に動かす。13 日は既存のスケジュール（1、4、7、10、16、19、22、25、28 日）の空きで、3 日おきの並びに収まる
- `targets.toml` に `monthly-zabbix-rewse-jp` を足し、指摘は `ansible-playbooks` に送る
- `tests/test_infra.py` の `HOME_SITES` と `SCHEDULE_DAYS` を更新する
- `HomeTargetDomainApex` のコメントから `zabbix.rewse.jp` を外す
- TXT レコードを作ってドメインを検証してから、`security-agent-deploy` プロファイルで反映する。手順は security-agent の `docs/setup.md` に従う

## 公開前の確認

インターネットに開く前に、Zabbix の設定を API で読んで次を確かめる。満たしていなければ、開く前に直す。

- Guest ユーザーが無効で、Guests グループの画面アクセスも無効である
- 画面にログインできるユーザーは全員 MFA が必須である
- 初期ユーザー `Admin` が残っているなら、パスワードが初期値ではない

## 反映の順番

1. cloudfront-waf の `RateLimitLogin` を反映する。画面を開く前にレート制限を効かせるためである
2. ansible-playbooks で `zabbix_server` を fox に反映する（`zabbix_server_apache` と `zabbix_server_fail2ban`）
3. 家の外（スマートフォンのモバイル回線など）から `https://zabbix.rewse.jp/zabbix/` が開けること、`https://rewse.jp/zabbix/` と `https://zabbix.rewse.jp/zabbix/api_jsonrpc.php` が 403 になることを確かめる。fail2ban の `zabbix-web` が両方のログを読んでいることを `fail2ban-client get zabbix-web logpath` で確かめる
4. security-agent のドメインを検証し、pentest とスケジュールを反映する

## 実装者に任せること

- テストを既存のどのファイルに足すか、新しいファイルにするか
- vhost とフィルタのコメントの文面
- `RedirectMatch` か `RewriteRule` か
