# zabbix.rewse.jp の IP 制限撤廃 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IntelliTrend Mobile と画面を、5G 回線から `https://zabbix.rewse.jp/zabbix/` で使えるようにする。`Admin` からは API を取り上げる。

**Architecture:** fox の Apache に `zabbix.rewse.jp` 専用の vhost を足し、その中だけ `/zabbix` を全員に開く。API の守りは Zabbix の権限で分ける（アプリは読み取りユーザーのトークン、MCP は専用ユーザーのトークン、`Admin` は API なし）。そのうえで WAF のレート制限、fail2ban、月次 pentest を重ねる。

**Tech Stack:** Apache 2.4、fail2ban、Ansible、Zabbix 7.4 API、AWS CloudFormation（WAFv2、Security Agent、EventBridge Scheduler）、pytest、1Password CLI

**Spec:** `docs/superpowers/specs/2026-11-02-zabbix-public-access-design.md`

## Global Constraints

- Zabbix の URL は `https://zabbix.rewse.jp/zabbix/` のまま。公式の `/etc/apache2/conf-available/zabbix.conf` は書き換えない
- `rewse.jp/zabbix` などデフォルト vhost 側の `Require ip` は変えない。zabbix-mcp-server の URL（`https://rewse.jp/zabbix/`）も変えない
- WAF: `RateLimitLogin` に `STARTS_WITH /zabbix/index` を足す。`RateLimitZabbixApi` は `/zabbix/api_jsonrpc.php` で始まるパスに対し、IP ごとに 300 リクエスト / 300 秒を超えたら Block する
- pentest: Title `monthly-zabbix-rewse-jp`、エンドポイント `https://zabbix.rewse.jp/zabbix/`、毎月 13 日 21:15 UTC（`cron(15 21 13 * ? *)`）。中身は `SitePentestNas` と同じ
- 読み取りロールの API 許可リストは `*.get` と `user.logout` だけにする
- トークンとパスワードの値は、端末にも会話にもログにも出さない。`op read` からパイプで渡す。1Password への書き込みは `op item create` と `op item edit` で行う
- 1Password の項目名は `System - Consumer` 形式にする。コミットには Secret Reference（項目 ID）だけを書く
- ansible-playbooks の `~/git/ansible-playbooks` の作業ツリーは、別セッションが `feat/mailboxd` で使っている。この計画の作業は、`git -C ~/git/ansible-playbooks worktree add /tmp/ap-zabbix-impl -b feat/zabbix-public main` で作った worktree で行う
- 検証コマンド:
  - ansible-playbooks: `uv run --with pytest --with ansible-core pytest tests` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
  - cloudfront-waf: `uv run pytest -q`、`uv run cfn-lint infra/deploy-role.yaml infra/template.yaml`、pre-commit
  - security-agent: `uv run pytest -q`、pre-commit
- コミットメッセージは Conventional Commits で英語にする。push と外部への書き込み（AWS への反映、Zabbix の変更、1Password の変更）は、それぞれ実行する前にユーザーに確認する

## Review Focus

- `zabbix.rewse.jp` の API は外から 200、`rewse.jp/zabbix/api_jsonrpc.php` は外から 403 になる。Apache の Location のマージ順で決まるので、単体テストでは確かめられない。Task 5 Step 3 で、家の外にある alfa から実際に呼んで確かめる
- 画面へのログインを無効にしたユーザーでも、トークンで API が通る。通らないとアプリも MCP も止まる。Task 2 Step 5 で、グループを作った直後に確かめる
- 読み取りグループに入れていないホストグループのホストは、アプリに出てこない。Task 2 Step 2 で、今あるホストグループをすべて読み取りにする。あとから作ったホストグループは手で足す必要があるので、そのことを Task 2 Step 3 で 1Password 項目のメモに書く
- fail2ban の新しいフィルタが、正常な API の `POST /zabbix/api_jsonrpc.php`（200）を失敗として数えない。Task 4 Step 1 のテストで確かめる
- `Admin` のロールを替えると、作業に使っているトークンも使えなくなる。Task 3 は、Task 2 で作った MCP 用の新しいトークンで行う

---

### Task 1: WAF のレート制限（cloudfront-waf）

**Files:**
- Modify: `~/git/cloudfront-waf/infra/template.yaml`（`RateLimitLogin` は 164 行目付近、`RateLimitAll` は 208 行目付近）
- Modify: `~/git/cloudfront-waf/tests/test_template.py`（`RULE_ORDER`、`test_rate_limits`）
- Modify: `~/git/cloudfront-waf/README.md`（ルールの表）

**Interfaces:**
- Produces: WAF のルール `RateLimitZabbixApi`（Priority 4）。`RateLimitAll` 以降のルールは Priority を 1 つずつ下げる（5 から 12）

- [ ] **Step 1: `git pull` して、失敗するテストを書く**

`RULE_ORDER` の `RateLimitLogin` の直後に `"RateLimitZabbixApi"` を入れる。`test_rate_limits` の期待するパスの集合を `{"/api/login", "/auth/", "/login", "/zabbix/index"}` にする。新しいテストを足す。

```python
def test_zabbix_api_rate_limit(template: dict[str, Any]) -> None:
    rule = _rules(template)["RateLimitZabbixApi"]
    rate = rule["Statement"]["RateBasedStatement"]
    assert rule["Action"] == {"Block": {}}
    assert rate["Limit"] == 300
    assert rate["EvaluationWindowSec"] == 300
    assert rate["AggregateKeyType"] == "IP"
    match = rate["ScopeDownStatement"]["ByteMatchStatement"]
    assert match["FieldToMatch"] == {"UriPath": {}}
    assert match["PositionalConstraint"] == "STARTS_WITH"
    assert match["SearchString"] == "/zabbix/api_jsonrpc.php"
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest -q tests/test_template.py`
Expected: `test_rate_limits`、`test_zabbix_api_rate_limit`、ルール順のテストが FAIL

- [ ] **Step 3: テンプレートと README を直す**

`RateLimitLogin` の `OrStatement` に、ほかと同じ形（`UriPath`、`STARTS_WITH`、`LOWERCASE`）で `/zabbix/index` を足す。上のコメントに、Zabbix の画面のログイン（`/zabbix/index.php` と `/zabbix/index_mfa.php`）を足す。`RateLimitZabbixApi` を Priority 4 で足し、`MetricName` はルール名と同じにする。コメントには上限の根拠を書く（アプリは多いときで 10 分に 15 回、fox の MCP は CloudFront を通らない）。README の表に行を足し、`RateLimitLogin` の行に `/zabbix/index` を足す。

- [ ] **Step 4: 検証する**

Run: `uv run pytest -q && uv run cfn-lint infra/deploy-role.yaml infra/template.yaml && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

```bash
git add infra/template.yaml tests/test_template.py README.md
git commit -m "feat: rate-limit the Zabbix login and API"
```

- [ ] **Step 6: ユーザーに確認してから反映する**

Run: `AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh`
Expected: スタックの更新が完了する。`aws wafv2 get-web-acl ... | cat` で、`RateLimitZabbixApi` が Priority 4 にあることを確かめる

### Task 2: 読み取りユーザーと MCP 用ユーザー（Zabbix と 1Password）

コードの変更はない。Zabbix API は、家の Mac から `https://rewse.jp/zabbix/api_jsonrpc.php` で呼ぶ。読み出しには `mcporter call zabbix.<tool>` を使ってよい。トークンやパスワードの値が出力に含まれる呼び出し（`token.generate`、`user.create`）だけは、`curl` と `jq` を使い、値を直接 `op item edit` に渡す。認証には、今の `zabbix-mcp` トークン（`op://ansible/qbgipeerfcsiwsudnejpmwl2oy/credential`）を `Authorization: Bearer` で使う。

**Interfaces:**
- Produces:
  - 1Password `ansible` の新しい項目 `Zabbix - IntelliTrend Mobile`。`username`、`password`、トークンを入れる `credential` を持つ
  - MCP 用の項目 `qbgipeerfcsiwsudnejpmwl2oy`。`credential` を新しいトークンに書き換え、MCP 用ユーザーの `username` と `password` を足す
  - Zabbix のロール 3 つ。名前は実装者が決める。この計画では仮に「読み取りロール」「MCP ロール」「API なし Super admin ロール」と呼ぶ
  - ユーザーグループ 2 つ（読み取りグループ、MCP グループ）とユーザー 2 つ

- [ ] **Step 1: 前提を確かめる**

Zabbix 7.4 の文書で次を確かめて、結果をユーザーに報告する。
- 組み込みの Super admin ロール（roleid 3）を持つユーザーが 1 人もいなくなってよいか
- `gui_access` を無効（3）にしたグループのユーザーが、トークンで API を使えるか

1 つ目が「いけない」なら、ここで止めてユーザーと扱いを決め直す。

- [ ] **Step 2: ユーザーに確認してから、ロールとグループを作る**

- 読み取りロール: `type` は 1（User）。`rules.api.access` は 1、`rules.api.mode` は 1（許可リスト）、`rules.api` は `["*.get", "user.logout"]`。`rules.ui.default_access` は 0、`rules.actions_default_access` は 0 とする
- MCP ロール: `type` は 3（Super admin）。`rules.api.access` は 1、`rules.api.mode` は 0（拒否リストで、中身は空）
- API なし Super admin ロール: `type` は 3。`rules.api.access` は 0。ほかは組み込みの Super admin ロールと同じにする
- 読み取りグループ: `gui_access` は 3。`hostgroup_rights` で、`hostgroup.get` が返すすべてのホストグループに `permission` 2（読み取り）を与える
- MCP グループ: `gui_access` は 3

- [ ] **Step 3: 1Password の項目とユーザーを作る**

`op item create` の `--generate-password` で、`Zabbix - IntelliTrend Mobile` を `ansible` に作る。メモには、あとから作ったホストグループは読み取りグループに手で足す必要があることを書く。MCP 用の項目には、`op item edit` で `username` と、生成した `password` を足す。各ユーザーは `user.create` で作り、パスワードは `op read` から渡す。ロールとグループは Step 2 のものにする。

- [ ] **Step 4: トークンを発行して 1Password に入れる**

各ユーザーに `token.create`（`expires_at` は 0）と `token.generate` を行う。返ってきた `token` は `jq -r` で取り出し、端末に出さずにそのまま `op item edit <item> credential=...` に渡す。

- [ ] **Step 5: トークンで API が通ることを確かめる**

それぞれの新しいトークンで `host.get`（`limit: 1`）を呼び、結果が返ることを確かめる。読み取りトークンで `host.update` を呼ぶと拒否されることも確かめる。どちらかのトークンで `host.get` が通らないなら、そのグループの `gui_access` を 0 に戻して、もう一度確かめる。

- [ ] **Step 6: MCP を新しいトークンに切り替える**

Run（`/tmp/ap-zabbix-impl` で）: `direnv exec . ansible-playbook home-primary.yml --tags zabbix_mcp`
Expected: `/etc/zabbix-mcp/config.toml` が changed になり、サービスが再起動する。そのあと `mcporter call zabbix.host_get limit=1` が結果を返す

### Task 3: `Admin` から API を取り上げる（Zabbix）

**Interfaces:**
- Consumes: Task 2 の MCP 用の新しいトークン（`op://ansible/qbgipeerfcsiwsudnejpmwl2oy/credential`）と、API なし Super admin ロール

- [ ] **Step 1: ユーザーに確認してから、`Admin` のロールを替える**

`user.update` で、`Admin`（userid 1）の `roleid` を API なし Super admin ロールにする。この時点で古いトークン 2 つは使えなくなり、アプリは Task 6 まで使えない。

- [ ] **Step 2: 古いトークンを削除する**

`token.delete` で、`token.get` の `userid` が 1 のトークン（`IntelliTrend Mobile`、`zabbix-mcp`）を消す。

- [ ] **Step 3: 公開前の確認をする**

次をすべて確かめて、結果をユーザーに報告する。1 つでも満たさないなら、Task 5 の反映には進まない。
- `user.get` で、Guest ユーザーが無効グループ（Disabled）に入っていて、Guests グループの `gui_access` が 3 である
- 画面にログインできる各ユーザーグループの `mfa_status` が 1（MFA 必須）である
- `Admin` のパスワードで `user.login` を呼ぶと、API が使えないとして拒否される。パスワードはユーザーに入力してもらう
- `token.get` が返すのが、読み取りユーザーと MCP 用ユーザーの 2 つだけである
- `mcporter call zabbix.host_get limit=1` が今も結果を返す

`Admin` のパスワードが初期値でないかの確認は、ユーザーに頼む。

### Task 4: `zabbix.rewse.jp` の vhost と fail2ban（ansible-playbooks）

**Files:**
- Create: `roles/zabbix_server/templates/zabbix.rewse.jp.conf.j2`
- Create: `roles/zabbix_server/tasks/apache.yml`
- Create: `roles/zabbix_server/templates/fail2ban-filter.conf.j2`（`files/fail2ban-filter.conf` から `git mv` する）
- Modify: `roles/zabbix_server/vars/main.yml`、`roles/zabbix_server/tasks/main.yml`、`roles/zabbix_server/tasks/fail2ban.yml`、`roles/zabbix_server/templates/fail2ban-jail.conf.j2`、`roles/zabbix_server/templates/zabbix-api.conf.j2`（コメントだけ）
- Test: `tests/test_internet_exposure.py`

**Interfaces:**
- Produces: 変数 `zabbix_server_hostname: zabbix.rewse.jp`、タグ `zabbix_server_apache`
- テストのヘルパー:
  - `render_vhost(role: pathlib.Path, name: str, **variables) -> str`: 今の関数に、テンプレートへ渡す変数を足す
  - `filter_regexes(path: pathlib.Path, variable: str, hostname: str) -> list[re.Pattern]`: 新しく足す。`failregex =` の行とその継続行（インデントされた行）をすべて読み、`filter_regex` と同じ置き換えをする

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_internet_exposure.py` に `ZABBIX_SERVER = ROLES / "zabbix_server"` と `ZabbixPublicVhostTest` を足す。

- `test_vhost_is_deployed_from_the_template`: `vhost_deploy_task(ZABBIX_SERVER, "zabbix.rewse.jp")["dest"]` が `/etc/apache2/sites-available/{{ zabbix_server_hostname }}.conf` である。`tasks/main.yml` が `apache.yml` を `zabbix_server_apache` タグで読み込む
- `test_vhost_opens_zabbix_to_everyone`: `render_vhost(ZABBIX_SERVER, "zabbix.rewse.jp.conf.j2", zabbix_server_hostname="zabbix.rewse.jp")` に `ServerName zabbix.rewse.jp`、`<Location "/zabbix">` の中の `Require all granted`、`RedirectMatch ^/$ /zabbix/` がある。`require_ip_blocks` の結果が空である
- `test_filter_matches_failed_logins_on_both_vhosts`: `filter_regexes(ZABBIX_SERVER / "templates" / "fail2ban-filter.conf.j2", "zabbix_server_hostname", "zabbix.rewse.jp")` について、次を確かめる
  - どれかに一致し、`host` が `203.0.113.7` になる: `access_line("zabbix.rewse.jp", "POST /zabbix/index.php", 200)`、`access_line("zabbix.rewse.jp", "POST /zabbix/index_mfa.php", 200)`、combined 形式の `'203.0.113.7 - - [] "POST /zabbix/index.php HTTP/1.1" 200 28 "-" "curl" 512'`
  - どれにも一致しない: `access_line("zabbix.rewse.jp", "POST /zabbix/index.php", 302)`、`access_line("zabbix.rewse.jp", "POST /zabbix/api_jsonrpc.php", 200)`、`access_line("nas.rewse.jp", "POST /zabbix/index.php", 200)`
- `test_jail_reads_both_logs`: `jail(ZABBIX_SERVER / "templates" / "fail2ban-jail.conf.j2", "zabbix-web")["logpath"].split()` が `["/var/log/apache2/access.log", "/var/log/apache2/other_vhosts_access.log"]` である

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_internet_exposure.py -k ZabbixPublicVhost`
Expected: 4 つとも FAIL

- [ ] **Step 3: 実装する**

- vhost: `nas.rewse.jp.conf.j2` と同じ形にする（`ServerAdmin`、証明書の 3 行）。プロキシの設定はない。コメントには次の 3 つを書く
  - サーバー全体の `<Location>` より後にマージされるので、この vhost では画面も API も開く
  - API は Zabbix のロールで守る
  - デフォルト vhost の `/zabbix` は `zabbix-api.conf.j2` が引き続き絞る
- `tasks/apache.yml`: `roles/filebrowser/tasks/apache.yml` と同じ 2 タスクにする
- フィルタ: `failregex` を 2 行にする（今の行と、`^{{ zabbix_server_hostname | regex_escape }}:\d+ <HOST> ...` の行）
- jail: `logpath` を 2 行にする
- `fail2ban.yml`: フィルタのタスクを `copy` から `template` に変える
- `zabbix-api.conf.j2`: 「Nothing beyond the LAN needs it」の段落を、設計どおりの説明に書き換える

- [ ] **Step 4: 検証する**

Run: `uv run --with pytest --with ansible-core pytest tests && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: すべて PASS。`test_privilege_hardening.py` の `ZabbixFrontendTest` と `test_fail2ban_apache.py` の `JailActionTest` も含む

- [ ] **Step 5: コミットする**

```bash
git add roles/zabbix_server tests/test_internet_exposure.py
git commit -m "feat(zabbix_server): serve zabbix.rewse.jp to the internet"
```

### Task 5: fox に反映して外から確かめる

**Interfaces:**
- Consumes: Task 1（WAF が反映済み）、Task 3（公開前の確認が通っている）、Task 4 のブランチ

- [ ] **Step 1: check モードで差分を見る**

Run（`/tmp/ap-zabbix-impl` で）: `direnv exec . ansible-playbook home-primary.yml --tags zabbix_server_apache,zabbix_server_fail2ban --check --diff`
Expected: vhost、`a2ensite`、フィルタ、jail だけが changed になる

- [ ] **Step 2: ユーザーに確認してから反映する**

Run: Step 1 のコマンドから `--check --diff` を外したもの
Expected: failed が 0 で、Apache の reload と fail2ban の restart が起きる

- [ ] **Step 3: 外から確かめる**

alfa（家の外にあり、CloudFront を通る）で次を確かめる。トークンは Mac で `op read` して、`ssh alfa.rewse.jp` の標準入力から `curl -H @-` に `Authorization: Bearer ...` として渡す。
- `https://zabbix.rewse.jp/zabbix/` が 200
- `https://zabbix.rewse.jp/` が 302 で、`Location` が `/zabbix/`
- 読み取りトークンで `https://zabbix.rewse.jp/zabbix/api_jsonrpc.php` に `host.get` を POST すると 200 で、`result` がある
- `https://rewse.jp/zabbix/` と `https://rewse.jp/zabbix/api_jsonrpc.php` が 403

fox で `sudo fail2ban-client get zabbix-web logpath` を実行し、2 つのログが返ることを確かめる。

### Task 6: IntelliTrend Mobile を切り替える（ユーザー）

- [ ] **Step 1: ユーザーに頼む**

アプリの接続先を `https://zabbix.rewse.jp/zabbix/` にし、認証を `Zabbix - IntelliTrend Mobile` のトークンにしてもらう。

- [ ] **Step 2: 5G 回線で確かめてもらう**

アプリで監視状況が見られること、ブラウザで `https://zabbix.rewse.jp/zabbix/` に MFA 付きでログインできることを確かめてもらう。fox の `other_vhosts_access.log` に、5G の IPv6 から `zabbix.rewse.jp` への `POST /zabbix/api_jsonrpc.php` 200 があることを確かめる。

### Task 7: pentest の対象ドメイン（security-agent、1 回目の反映）

`HomeTargetDomainsVerified=true` のまま、検証前のドメインを pentest に使うと反映に失敗する。そのため、ドメインと pentest は 2 回に分けて反映する。

**Files:**
- Modify: `~/git/security-agent/infra/template.yaml`（`HomeTargetDomainTeslamate` の後、`AgentSpace` の `TargetDomainIds`、`HomeTargetDomainApex` のコメント）
- Test: `~/git/security-agent/tests/test_infra.py`

**Interfaces:**
- Produces: リソース `HomeTargetDomainZabbix`

- [ ] **Step 1: `git pull` して、失敗するテストを書く**

`test_infra.py` に `test_zabbix_target_domain_is_attached` を足す。`HomeTargetDomainZabbix` の `Type` が `AWS::SecurityAgent::TargetDomain`、`TargetDomainName` が `zabbix.rewse.jp`、`VerificationMethod` が `DNS_TXT` であり、`AgentSpace` の `TargetDomainIds` に `HomeTargetDomainZabbix.TargetDomainId` の `GetAtt` があることを確かめる。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest -q tests/test_infra.py`
Expected: 新しいテストが FAIL

- [ ] **Step 3: 実装する**

`HomeTargetDomainZabbix` を足し、`TargetDomainIds` の末尾にも足す。`HomeTargetDomainApex` のコメントから `zabbix.rewse.jp` を外す。

- [ ] **Step 4: 検証してコミットする**

Run: `uv run pytest -q && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: PASS

```bash
git add infra/template.yaml tests/test_infra.py
git commit -m "feat: register zabbix.rewse.jp as a pentest target domain"
```

- [ ] **Step 5: ユーザーに確認してから反映し、ドメインを検証する**

`docs/setup.md` step 10 の 3 のコマンドを `AWS_PROFILE=security-agent-deploy` で実行し、`infra/scripts/configure-pr-review.sh` も実行する。そのあと step 5 の手順で `zabbix.rewse.jp` を検証する（One-click verification か TXT レコード）。
Expected: `zabbix.rewse.jp` が `VERIFIED` になる

### Task 8: zabbix.rewse.jp の月次 pentest（security-agent、2 回目の反映）

**Files:**
- Modify: `~/git/security-agent/infra/template.yaml`（`SitePentestNas` と `SiteScheduleNas` の近く）
- Modify: `~/git/security-agent/targets.toml`、`~/git/security-agent/docs/setup.md`（step 10 の本文）
- Test: `~/git/security-agent/tests/test_infra.py`（`HOME_SITES`、`SCHEDULE_DAYS`）

**Interfaces:**
- Consumes: Task 7 の `HomeTargetDomainZabbix`（`VERIFIED`）

- [ ] **Step 1: 失敗するテストを書く**

`HOME_SITES` に `"zabbix.rewse.jp": "Zabbix"`、`SCHEDULE_DAYS` に `"SitePentestZabbix": 13` を足す。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run pytest -q tests/test_infra.py`
Expected: `SitePentestZabbix` がないので FAIL

- [ ] **Step 3: 実装する**

`SitePentestNas` と `SiteScheduleNas` を写して、`SitePentestZabbix` と `SiteScheduleZabbix` を作る。値は Global Constraints のとおりにする。スケジュールの `Name` は `security-agent-monthly-zabbix-rewse-jp` で、`Description` は nas と同じ書き方にする。`targets.toml` には、`monthly-zabbix-rewse-jp` を `repository = "ansible-playbooks"` でタイトル順の位置に足す。`docs/setup.md` step 10 では、サイトの一覧と日付の一覧に `zabbix`（13 日）を足し、「nine domains」を「ten domains」にする。

- [ ] **Step 4: 検証してコミットする**

Run: `uv run pytest -q && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: PASS

```bash
git add infra/template.yaml targets.toml docs/setup.md tests/test_infra.py
git commit -m "feat: pentest zabbix.rewse.jp monthly"
```

- [ ] **Step 5: ユーザーに確認してから反映する**

Task 7 Step 5 と同じコマンドで反映し、`configure-pr-review.sh` を実行する。
Expected: スタックの更新が完了する。`aws scheduler get-schedule --group-name <PentestScheduleGroup の名前> --name security-agent-monthly-zabbix-rewse-jp --region us-east-1 | cat` が `cron(15 21 13 * ? *)` を返す

### Task 9: 仕上げ

- [ ] **Step 1: ansible-playbooks を main に入れる**

`feat/zabbix-public` を main にマージする。同じコミットで、spec と計画を `docs/superpowers/archive/specs/` と `docs/superpowers/archive/plans/` に `git mv` する。

- [ ] **Step 2: ユーザーに確認してから push する**

ansible-playbooks、cloudfront-waf、security-agent をそれぞれ push する。ansible-playbooks の main には、別セッションの mailboxd の docs コミットも載っている。push してよいかは、そのことも含めてユーザーに確認する。

- [ ] **Step 3: worktree を片付ける**

Run: `git -C ~/git/ansible-playbooks worktree remove /tmp/ap-zabbix-impl && git -C ~/git/ansible-playbooks worktree remove /tmp/ap-zabbix`
