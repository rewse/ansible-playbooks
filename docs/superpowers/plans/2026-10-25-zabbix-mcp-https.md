# zabbix-mcp-server の HTTPS 化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox の zabbix-mcp-server を Apache の vhost `https://zabbix-mcp.rewse.jp/mcp` の裏に置き、家、VPN、会社からだけ使えるようにする。

**Architecture:** zabbix-mcp-server は `127.0.0.1:8081` だけで待ち受け、Apache が TLS を終端して `Require ip` で接続元を絞る。会社からは cloudfront-waf の CloudFront と WAF を通り、家と VPN からは UniFi の DNS で fox に直接届く。トークンの誤りで返る 401 は fail2ban が拾う。

**Tech Stack:** Ansible、Apache（mod_proxy_http）、fail2ban、pytest（unittest、jinja2、PyYAML、tomllib）、CloudFormation（cloudfront-waf）、Route 53、UniFi、chezmoi

**Spec:** `docs/superpowers/specs/2026-10-25-zabbix-mcp-https-design.md`

## Global Constraints

- ホスト名は `zabbix-mcp.rewse.jp`（`zabbix_mcp_hostname`）、ポートは `8081`（`zabbix_mcp_port`）、`public_url` は `https://{{ zabbix_mcp_hostname }}`、待ち受けは `127.0.0.1`
- vhost が許可する接続元は `127.0.0.1`、`::1`、`networks` の `home_private_ipv4`、`home_private_ipv6`、`home_public_ipv4`、`home_public_ipv6`、`aws_private_ipv4`、`aws_public_ipv6`、`office_public_ipv4`（リストなので `join(' ')`）だけ
- 証明書は `/etc/letsencrypt/live/rewse.jp/fullchain.pem` と `privkey.pem`、`Include /etc/letsencrypt/options-ssl-apache.conf`
- fail2ban のジェイル名とフィルタ名は `zabbix-mcp`、ログは `/var/log/apache2/other_vhosts_access.log`
- `[reporting] download_urls = false` を保つ
- 対象ホストは fox だけで、プレイブックは `home-primary.yml`
- AGENTS.md の Ansible の規約に従う。filebrowser が見本で、タスク名は `<component> | ...`、テンプレートの先頭は `{{ ansible_managed | comment }}`、`mode` は `"0644"` のような 4 桁の文字列、`command` には理由のコメントと `changed_when` を付ける
- コメントは英語で、今のコードについて書く。変更の経緯はコミットメッセージに書く
- check mode は非破壊で失敗しない。2 回目の実行は `changed=0`
- コミットメッセージは Conventional Commits。push の前に `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests` を通す。新しいファイルは先に stage する
- main への push、AWS、UniFi、chezmoi への書き込み、fox への反映は、それぞれ実施の前にユーザーの確認を取る
- 120 秒を超える ansible-playbook は `nohup sh -c '... > LOG 2>&1; echo EXIT=$? >> LOG' > /dev/null 2>&1 &` で走らせ、`EXIT=` の行で終了コードを確かめる

## Review Focus

- Streamable HTTP の応答が server-sent events のとき、Apache が溜め込むとクライアントが待ち続ける。`ProxyPass` の `flushpackets=on` を Task 2 のテストで固定する
- Apache が Host ヘッダーを書き換えると、zabbix-mcp-server は `public_url` と一致しないとして全リクエストを拒否する。`ProxyPreserveHost on` を Task 2 のテストで固定する
- 許可していない接続元が、有効なトークンを持って CloudFront 経由で来たら 403 になる。`Require ip` の値が一覧と過不足なく一致し、`Require all granted` がないことを Task 2 のテストで固定する
- クライアントがトークンを送る前に読む `/.well-known/` の 401、ほかの vhost の 401、成功した呼び出しで ban しない。Task 3 のテストで一致しない行として固定する
- トークンが空のとき、認証なしで公開されてはならない。設定が TOML として読めず、サービスが起動しないことを Task 1 のテストで固定する

---

### Task 1: zabbix-mcp-server をループバックで待ち受け、https の public_url を名乗る

**Files:**
- Create: `tests/test_zabbix_mcp.py`
- Modify: `roles/zabbix_mcp/vars/main.yml`
- Modify: `roles/zabbix_mcp/templates/config.toml.j2`（作業ツリーにある `[reporting]` の追加もこのコミットに含める）

**Interfaces:**
- Produces: 変数 `zabbix_mcp_hostname: zabbix-mcp.rewse.jp`、`zabbix_mcp_port: 8081`、`zabbix_mcp_public_url: "https://{{ zabbix_mcp_hostname }}"`
- Produces: テストの補助 `render(name: str, **overrides) -> str`。`roles/zabbix_mcp/templates` を読む jinja2 の環境（`StrictUndefined`）に、`comment`、`mandatory`（値をそのまま返す。Ansible でも定義済みの文字列はそのまま返る）、`regex_escape`（`re.escape`）を足す。`vars/main.yml` の `zabbix_mcp_hostname` と `zabbix_mcp_port`、`zabbix_mcp_public_url=f"https://{hostname}"`、偽のトークンと Zabbix の URL、`ansible_managed`、`networks` で描画し、`overrides` で上書きする。`networks` の偽の値は 7 個のキーを持ち、`office_public_ipv4` だけリスト（例 `["198.51.100.0/24", "203.0.113.0/24"]`）にする。Task 2 と Task 3 も使う

- [ ] **Step 1: 失敗するテストを書く**

`ZabbixMcpServerTest` に次を書く。

```python
    def test_server_listens_on_loopback_only(self):
        server = tomllib.loads(render("config.toml.j2"))["server"]
        self.assertEqual(server["host"], "127.0.0.1")
        self.assertEqual(server["port"], 8081)

    def test_public_url_is_the_apache_vhost(self):
        variables = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())
        self.assertEqual(variables["zabbix_mcp_hostname"], "zabbix-mcp.rewse.jp")
        self.assertEqual(
            variables["zabbix_mcp_public_url"], "https://{{ zabbix_mcp_hostname }}"
        )

    def test_report_download_links_stay_off(self):
        config = tomllib.loads(render("config.toml.j2"))
        self.assertIs(config["reporting"]["download_urls"], False)

    def test_empty_auth_token_fails_closed(self):
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads(render("config.toml.j2", zabbix_mcp_auth_token=""))
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_mcp.py -v`
Expected: FAIL（`vars/main.yml` に `zabbix_mcp_hostname` と `zabbix_mcp_port` がなく `render` が KeyError になる。`host` は `0.0.0.0`）

- [ ] **Step 3: 変数と設定を直す**

`vars/main.yml` に `zabbix_mcp_hostname` と `zabbix_mcp_port` を足し、`zabbix_mcp_public_url` を `https://{{ zabbix_mcp_hostname }}` にする。`config.toml.j2` は `host = "127.0.0.1"`、`port = {{ zabbix_mcp_port }}` にし、Apache が TLS を終端してこのループバックに中継する旨のコメントを付ける。`auth_token` のガードの文言は、Apache が LAN と会社に公開するので必須、という趣旨にする。`download_urls = false` のコメントは、ダウンロードの経路がベアラートークンなしで PDF を配る、という理由だけにする。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_mcp.py -v`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add tests/test_zabbix_mcp.py roles/zabbix_mcp/vars/main.yml roles/zabbix_mcp/templates/config.toml.j2
git commit -m "feat(zabbix_mcp): listen on loopback for an https public URL"
```

コミットメッセージの本文に、レポートのダウンロードリンクを止めたことも書く。

### Task 2: Apache の vhost で TLS を終端し、接続元を絞る

**Files:**
- Create: `roles/zabbix_mcp/templates/zabbix-mcp.rewse.jp.conf.j2`
- Create: `roles/zabbix_mcp/tasks/apache.yml`
- Create: `roles/zabbix_mcp/meta/main.yml`
- Modify: `roles/zabbix_mcp/tasks/main.yml`
- Modify: `roles/zabbix_mcp/handlers/main.yml`
- Test: `tests/test_zabbix_mcp.py`

**Interfaces:**
- Consumes: Task 1 の変数と `render`
- Produces: `tasks/main.yml` の `apache.yml` の import（タグ `zabbix_mcp_apache`）、`meta/main.yml` の依存 `httpd`（タグ `httpd`）、ハンドラ `Reload Apache`（`roles/httpd/handlers/main.yml` と同じ本体）

- [ ] **Step 1: 失敗するテストを書く**

`ZabbixMcpApacheTest` に次を書く。

- `test_apache_component_is_imported`: `tasks/main.yml` の import が `user.yml`、`app.yml`、`service.yml`、`apache.yml` の順で始まり、`apache.yml` のタグが `["zabbix_mcp_apache"]`。`meta/main.yml` の依存に `httpd` がある
- `test_vhost_proxies_to_the_loopback_listener`: 描画した vhost の各行を strip したものに `ServerName zabbix-mcp.rewse.jp`、`ProxyPreserveHost on`、`ProxyPass / http://127.0.0.1:8081/ flushpackets=on`、`ProxyPassReverse / http://127.0.0.1:8081/`、`SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem` がある
- `test_vhost_allows_only_listed_networks`: `Require ip` の行の値を集めた集合が、`127.0.0.1`、`::1`、`render` に渡した `networks` の 7 個のキーの値（`office_public_ipv4` は要素ごと）と等しい。`Require all granted` がない

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_mcp.py -v`
Expected: FAIL（`apache.yml`、`meta/main.yml`、vhost のテンプレートがない）

- [ ] **Step 3: apache コンポーネントを作る**

filebrowser の `tasks/apache.yml` と同じ 2 タスクにする。`apache | Deploy vhost config` は `/etc/apache2/sites-available/{{ zabbix_mcp_hostname }}.conf` に `"0644"` で置き、`apache | Enable site` は `a2ensite {{ zabbix_mcp_hostname }}` を `'already enabled' not in` で判定する。どちらも `Reload Apache` を通知する。vhost は `<VirtualHost *:443>` に ServerAdmin `hostmaster@rewse.jp`、上のテストの行、`ProxyRequests off`、`<Location />` の `Require ip`、`SSLCertificateKeyFile`、`Include /etc/letsencrypt/options-ssl-apache.conf` を入れる。`flushpackets=on` と `localhost` でなく `127.0.0.1` を使う理由、`ProxyPreserveHost` が要る理由をコメントに書く。`meta/main.yml` は filebrowser と同じ書式で `httpd` を依存にする。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_mcp.py -v`
Expected: PASS

- [ ] **Step 5: コミットする**

```bash
git add roles/zabbix_mcp/templates/zabbix-mcp.rewse.jp.conf.j2 roles/zabbix_mcp/tasks/apache.yml roles/zabbix_mcp/meta/main.yml roles/zabbix_mcp/tasks/main.yml roles/zabbix_mcp/handlers/main.yml tests/test_zabbix_mcp.py
git commit -m "feat(zabbix_mcp): serve MCP over https through Apache"
```

### Task 3: トークンの誤りを fail2ban で止める

**Files:**
- Create: `roles/zabbix_mcp/templates/fail2ban-filter.conf.j2`
- Create: `roles/zabbix_mcp/templates/fail2ban-jail.conf.j2`
- Create: `roles/zabbix_mcp/tasks/fail2ban.yml`
- Modify: `roles/zabbix_mcp/tasks/main.yml`
- Modify: `roles/zabbix_mcp/meta/main.yml`
- Modify: `roles/zabbix_mcp/handlers/main.yml`
- Test: `tests/test_zabbix_mcp.py`

**Interfaces:**
- Consumes: Task 1 の `render`、Task 2 の `meta/main.yml`
- Produces: `fail2ban.yml` の import（タグ `zabbix_mcp_fail2ban`、`apache.yml` の後）、依存 `fail2ban`（タグ `fail2ban`、`httpd` の前）、ハンドラ `Restart fail2ban`（`roles/litellm/handlers/main.yml` と同じ本体）

- [ ] **Step 1: 失敗するテストを書く**

`ZabbixMcpFail2banTest` に次を書く。ログの行は `tests/test_internet_exposure.py` の `access_line` と同じ形（`f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl" 512'`）の関数をこのファイルに持つ。

- `test_fail2ban_component_is_imported`: `fail2ban.yml` のタグが `["zabbix_mcp_fail2ban"]`、`meta/main.yml` の依存に `fail2ban` がある
- `test_jail_reads_the_apache_log`: 描画したジェイルの `[zabbix-mcp]` が `enabled = true`、`backend = auto`、`filter = zabbix-mcp`、`logpath = /var/log/apache2/other_vhosts_access.log`
- `test_filter_matches_rejected_tokens_only`: `failregex` の `<HOST>` を `(?P<host>\S+)` に置き換えた正規表現が、`zabbix-mcp.rewse.jp` の `POST /mcp`、`GET /mcp`、`DELETE /mcp` の 401 に一致して `host` が `203.0.113.7` になる。`POST /mcp` の 200、`litellm.rewse.jp` の `POST /mcp` の 401、`GET /.well-known/oauth-protected-resource` の 401、`GET /mcpx` の 401 には一致しない

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_mcp.py -v`
Expected: FAIL（`fail2ban.yml` とテンプレートがない）

- [ ] **Step 3: fail2ban コンポーネントを作る**

filebrowser の `tasks/fail2ban.yml` と同じ 2 タスクで、`/etc/fail2ban/filter.d/zabbix-mcp.conf` と `/etc/fail2ban/jail.d/zabbix-mcp.conf` に置く。フィルタは `^{{ zabbix_mcp_hostname | regex_escape }}:\d+ <HOST> \S+ \S+ \[\] "\S+ /mcp(?:[/?]\S*)? HTTP/[\d.]+" 401 \d+` とし、401 が何を意味するか、`/.well-known/` を外す理由、vhost を固定する理由をコメントに書く。ジェイルは filebrowser のジェイルと同じ項目（`port = http,https`、`action = %(action_)s` と `apache-deny`）にする。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -v`
Expected: PASS（リポジトリのテスト全体）

- [ ] **Step 5: コミットする**

```bash
git add roles/zabbix_mcp/templates/fail2ban-filter.conf.j2 roles/zabbix_mcp/templates/fail2ban-jail.conf.j2 roles/zabbix_mcp/tasks/fail2ban.yml roles/zabbix_mcp/tasks/main.yml roles/zabbix_mcp/meta/main.yml roles/zabbix_mcp/handlers/main.yml tests/test_zabbix_mcp.py
git commit -m "feat(zabbix_mcp): ban addresses that send wrong MCP tokens"
```

### Task 4: サブドメインの規約と Zabbix API のコメントを直す

**Files:**
- Modify: `AGENTS.md`
- Modify: `roles/zabbix_server/templates/zabbix-api.conf.j2`

**Interfaces:**
- Consumes: Task 2 と Task 3 の vhost と fail2ban の形

- [ ] **Step 1: AGENTS.md にサブドメインの節を足す**

`## Repository Operations` の中に `### Subdomains` を英語で足す。spec の「AGENTS.md」の 5 項目（このリポジトリ、cloudfront-waf、UniFi、security-agent、chezmoi）を、手を入れる場所と反映の仕方が分かる粒度で書く。cloudfront-waf は `infra/template.yaml` の `Aliases`、`scripts/switch-dns.sh` の `SUBDOMAINS`、`tests/test_template.py` と `tests/test_switch_dns.py`、README と `docs/setup.md` の一覧を挙げ、反映は `AWS_PROFILE=admin scripts/deploy.sh` と `AWS_PROFILE=admin scripts/switch-dns.sh cloudfront` とする。security-agent は、インターネットのどこからでも届く名前に月次の pentest を `targets.toml` と `infra/template.yaml` に足してターゲットドメインを検証すること、接続元を絞る名前には作らないことを書く。段落は折り返さない。

- [ ] **Step 2: `zabbix-api.conf.j2` のコメントを直す**

MCP のポートは転送しておらず家の外のクライアントには経路がない、という文を、会社のクライアントは Apache の `zabbix-mcp.rewse.jp` を通って MCP サーバーに届き、MCP サーバーはこのホストから API を呼ぶので API は LAN の外に要らない、という内容にする。`Require` の行は変えない。

- [ ] **Step 3: 検証する**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure && uv run --with pytest --with ansible-core pytest tests`
Expected: すべて Passed

- [ ] **Step 4: コミットする**

```bash
git add AGENTS.md roles/zabbix_server/templates/zabbix-api.conf.j2
git commit -m "docs: list what a new rewse.jp subdomain touches"
```

### Task 5: cloudfront-waf に別名を足す

作業は `~/git/cloudfront-waf` で行う。先に `git pull` し、その AGENTS.md を読む。

**Files:**
- Modify: `tests/test_template.py`（`NAMES`）
- Modify: `tests/test_switch_dns.py`（`SUBDOMAINS`）
- Modify: `infra/template.yaml`（`Aliases`）
- Modify: `scripts/switch-dns.sh`（`SUBDOMAINS`）
- Modify: `README.md`、`docs/setup.md`

- [ ] **Step 1: テストの一覧に足す**

`NAMES` に `"zabbix-mcp.rewse.jp"`、`SUBDOMAINS` に `"zabbix-mcp"` を、どちらもアルファベット順（`zabbix` の後）で足す。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run pytest -q`
Expected: FAIL（テンプレートとスクリプトに `zabbix-mcp` がない）

- [ ] **Step 3: テンプレートとスクリプトに足す**

`Aliases` の `zabbix.rewse.jp` の後に `zabbix-mcp.rewse.jp`、`switch-dns.sh` の `SUBDOMAINS` の `"zabbix"` の後に `"zabbix-mcp"` を足す。

- [ ] **Step 4: ドキュメントを直す**

README の図のラベル（`rewse.jp and 9 subdomains`）と公開名の一覧、`docs/setup.md` の「ten public names」「nine subdomains」と一覧、`moves all ten names` を、11 個の公開名と 10 個のサブドメインに合わせる。README の「Turn on blocking」に、`zabbix-mcp.rewse.jp` への MCP の通信が誤検知されていないことを WAF のログで確かめてから有効にする旨を足す。

- [ ] **Step 5: 検証する**

Run: `uv run pytest -q && uv run cfn-lint infra/template.yaml && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: すべて通る

- [ ] **Step 6: コミットする**

```bash
git add tests/test_template.py tests/test_switch_dns.py infra/template.yaml scripts/switch-dns.sh README.md docs/setup.md
git commit -m "feat: serve zabbix-mcp.rewse.jp through CloudFront"
```

### Task 6: 切り替える

各ステップの書き込みの前にユーザーの確認を取る。`AWS_PROFILE=admin` を使う操作はこのワークステーションから実行できず、ユーザーが会社の Mac から実行する。そのステップに来たら、ユーザーに実行するコマンドと期待する結果を伝え、結果を受け取ってから次に進む。

- [ ] **Step 1: cloudfront-waf を push し、デプロイを頼む**

Run: `~/git/cloudfront-waf` で `git push` する。ユーザーには、会社の Mac で `git pull` してから `AWS_PROFILE=admin scripts/deploy.sh` を実行するよう頼む
Expected: ユーザーからスタックの更新が完了した報告を受ける。`curl -sS -o /dev/null -w '%{http_code}\n' --resolve zabbix-mcp.rewse.jp:443:<hass.rewse.jp の CloudFront のアドレス> https://zabbix-mcp.rewse.jp/` が TLS のエラーにならない（別名が CloudFront に登録された）

- [ ] **Step 2: 公開 DNS の作成を頼む**

ユーザーに、会社の Mac で `scripts/switch-dns.sh cloudfront --dry-run` の出力に `zabbix-mcp.rewse.jp.` の CNAME があることを見てから、`AWS_PROFILE=admin scripts/switch-dns.sh cloudfront` を実行するよう頼む
Expected: `curl -s 'https://dns.google/resolve?name=zabbix-mcp.rewse.jp&type=CNAME'` が CloudFront のドメイン名を返す

- [ ] **Step 3: UniFi の内部 DNS を足す**

UniFi の DNS ポリシーに、`zabbix-mcp.rewse.jp` を `fox.rewse.jp` に向ける CNAME を、ほかのサービス名と同じ形で足す。UI と Site Manager API（AGENTS.md の UniFi の節）のどちらでもよい。
Expected: 家の中で `dig +short zabbix-mcp.rewse.jp` が `fox.rewse.jp.` と `192.168.0.30` を返す

- [ ] **Step 4: ansible-playbooks を push して fox に反映する**

Run: `git -P fetch && git -P log --oneline HEAD..origin/main` が空であることを確かめてから push する。続けて `direnv exec . ansible-playbook home-primary.yml --tags zabbix_mcp_service,zabbix_mcp_apache,zabbix_mcp_fail2ban,zabbix_server_frontend --check --diff` で差分を確かめ、同じタグで反映し、もう一度 `--check` を流す
Expected: 反映は終了コード 0。変わるのは zabbix-mcp の設定、vhost、fail2ban のフィルタとジェイル、`zabbix-api.conf` のコメントだけ。2 回目は `changed=0`

- [ ] **Step 5: chezmoi の URL を変える**

`~/git/chezmoi` で `git pull` し、その AGENTS.md を読んでから、`dot_config/mcporter/private_mcporter.json.tmpl` の `zabbix` の `url` を `https://zabbix-mcp.rewse.jp/mcp` にしてコミットし、push する。この Mac で `chezmoi --no-pager apply ~/.config/mcporter/mcporter.json` を流す。`OP_SERVICE_ACCOUNT_TOKEN` が設定された環境では失敗するので、direnv の外で流す。会社の端末はユーザーが次に使うときに apply する
Expected: `rg -n 'zabbix-mcp.rewse.jp' ~/.config/mcporter/mcporter.json` が 1 行返る

- [ ] **Step 6: 家の中から確かめる**

- `curl -sS -o /dev/null -w '%{http_code}\n' https://zabbix-mcp.rewse.jp/health` が `200`
- `curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://zabbix-mcp.rewse.jp/mcp` が `401`
- `mcporter list zabbix` がツールの一覧を返す
- `nc -z -w 3 fox.rewse.jp 8081` が失敗する
- fox で `sudo fail2ban-client get zabbix-mcp logpath` が `/var/log/apache2/other_vhosts_access.log` を返し、`sudo fail2ban-regex /var/log/apache2/other_vhosts_access.log /etc/fail2ban/filter.d/zabbix-mcp.conf` が上の 401 に一致する

- [ ] **Step 7: CloudFront 経由で確かめる**

`https://dns.google/resolve?name=zabbix-mcp.rewse.jp&type=A` で得た CloudFront のアドレスを `curl --resolve zabbix-mcp.rewse.jp:443:<address>` に渡す。
- この Mac（家の公開アドレス）から `/health` が `200`
- alfa から `curl -4` で `/health` が `403`（alfa の公開 IPv4 は許可していない）

- [ ] **Step 8: 会社からの確認をユーザーに頼む**

次に出社したとき、`mcporter list zabbix` と `https://zabbix.rewse.jp/zabbix/` が使えることを確かめてもらう。どちらかが使えないときは、その時刻を聞いて WAF のログ（`aws-waf-logs-cloudfront-waf`）と fox の Apache のログを照らし合わせる。
