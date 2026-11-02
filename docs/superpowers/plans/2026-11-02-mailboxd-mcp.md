# mailboxd MCP サーバー 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox で psyb0t/docker-mailbox を動かし、Muse から家族 3 人の Sakura のメールを読み、整理し、下書きを作れるようにする。送信と完全削除はできない。

**Architecture:** 新しいロール `mailboxd` が Compose でコンテナを `127.0.0.1:8083` に立て、Apache の vhost `mail-mcp.rewse.jp` と fail2ban で守る。まず一時的な Cloudflare Quick Tunnel で Muse から確かめ、通ってから CloudFront、UniFi の DNS、security-agent を入れる。

**Tech Stack:** Ansible（community.docker.docker_compose_v2）、Docker Compose、Apache、fail2ban、1Password CLI、Python unittest + jinja2（テンプレートのテスト）

**Spec:** `docs/superpowers/specs/2026-11-02-mailboxd-mcp-design.md`

## Global Constraints

- ロール名 `mailboxd`、ホスト名 `mail-mcp.rewse.jp`、待ち受け `127.0.0.1:8083`（fox で 8080 から 8082 は使用中、8083 は空き）
- イメージ: `aged_release` の `oci:psyb0t/mailbox`、`pattern='^v\d+\.\d+\.\d+$'`、`tag@digest` で固定。`latest` と `sha-*` は使わない
- トークンの `scopes` は `[read, draft, organize]` だけ。`send`、`delete`、`admin` と `mailboxes: "*"` と文字列形式のトークンは使わない。各トークンの `mailboxes` は本人の 1 つだけ
- `smtp.host: smtp.invalid`、`smtp.password` は本物ではない固定の文字列、`send_guard.dry_run: true`
- IMAP: `rewse.sakura.ne.jp`、`port: 993`、`tls: ssl`
- コンテナのユーザーは uid 10001（上流の Dockerfile）。状態は `/srv/mailboxd` に置く
- 秘密は `/etc/compose/mailboxd/.env`（root、`"0600"`）だけに書き、`config.yaml` は `${VAR}` で参照する
- 公開リポジトリなので、家族のメールアドレスと名前、1Password の項目名をコミットしない。コミットするのは項目 ID だけ
- `watch`（webhook）は入れない。Apache の vhost に `Require ip` は付けない
- AGENTS.md の Ansible の規約（`roles/filebrowser` が手本）、タグ、タスク名、変数の接頭辞に従う
- コミットの前に `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests` を通す。新しいファイルは先に `git add` する

## Review Focus

- 他人のメールボックスを、名前ではなくメールアドレスで指定する。docker-mailbox の `mailbox` 引数は名前とアドレスの両方を受け付けるので、両方で拒否されること（Task 5 の確認に入れる）
- `reply` を `draft=false` で呼ぶ、`delete_message` を `permanent=true` で呼ぶ。`tools/list` に出なくても、`tools/call` を直接呼ばれたら拒否されること（Task 5）
- `.env` だけが変わったとき。`docker compose restart` は `env_file` を読み直さないので、ハンドラーはコンテナを作り直すこと（Task 2 のテスト）
- 大きな INBOX の検索が CloudFront の 60 秒のタイムアウトを越える。本番の経路で、各家族の INBOX の条件なしの検索が 60 秒以内に返ること（Task 7）
- MCP クライアントがトークンの前に `/.well-known/oauth-protected-resource` を読んで 401 を受ける。これで BAN されないこと（Task 4 のフィルタのテスト）

---

### Task 1: 1Password の項目をそろえる

利用者とのやり取りが要る。コミットはない。

**Interfaces:**
- Produces: Sakura の 3 項目の ID（`username` と `password` のフィールド）と、新しく作るトークンの 3 項目の ID（`credential` のフィールド）。Task 2 の `mailboxd_accounts` に入れる

- [ ] **Step 1: Sakura の 3 項目の場所を利用者に確かめる**

利用者に 3 項目の vault を尋ねる。`ansible` 以外にあれば、`ansible` vault に移すか複製するかを利用者に決めてもらい、その操作は利用者にしてもらう。

- [ ] **Step 2: トークンの項目を 3 つ作る**

項目名は `mailboxd - <家族の名前>`、カテゴリは API Credential、`credential` に `openssl rand -hex 32` の値を入れる。値は端末に出さず、`op item create` にパイプで渡す。

- [ ] **Step 3: Ansible と同じ環境で読めることを確かめる**

Run: 各項目について `direnv exec . op read op://ansible/<item-id>/username`（Sakura）と `direnv exec . op read op://ansible/<item-id>/credential`（トークン）を、出力を `wc -c` に流して実行する
Expected: どれも 0 より大きい長さが返る

### Task 2: config コンポーネント

**Files:**
- Create: `roles/mailboxd/vars/main.yml`、`roles/mailboxd/tasks/main.yml`、`roles/mailboxd/tasks/config.yml`、`roles/mailboxd/handlers/main.yml`、`roles/mailboxd/templates/config.yaml.j2`、`roles/mailboxd/templates/env.j2`
- Test: `tests/test_mailboxd.py`

**Interfaces:**
- Consumes: Task 1 の項目 ID
- Produces:
  - `mailboxd_accounts`: `[{password_item: <id>, token_item: <id>}]` の 3 要素
  - `mailboxd_hostname: mail-mcp.rewse.jp`、`mailboxd_port: 8083`、`mailboxd_data_dir: /srv/mailboxd`、`mailboxd_uid: 10001`
  - `mailboxd_trusted_authserv_id`: 最初は空文字。`config.yaml.j2` は空なら `trusted_authserv_id` を出さない。Task 5 で値を入れる
  - config.yml の `set_fact` `__mailboxd_mailboxes`: `[{name, address, password, token}]`。`address` は `op read op://ansible/<password_item>/username`、`name` は `address` のローカル部を小文字にし、`[^a-z0-9_-]` を `-` に置き換えたもの。`no_log: true`
  - 環境変数名: `MAILBOXD_PASSWORD_<NAME>` と `MAILBOXD_TOKEN_<NAME>`（`<NAME>` は `name` を大文字にして `-` を `_` にしたもの）
  - ハンドラー `Recreate mailboxd`: `community.docker.docker_compose_v2`、`project_src: /etc/compose/mailboxd`、`state: present`、`recreate: always`、`when: not ansible_check_mode`
  - テスト用の関数 `render(name, **overrides)`、`task_named(file, name)`（`roles/mailboxd/tasks/<file>` から名前の一致するタスクを返す）
  - タグ: `mailboxd_config`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_zabbix_mcp.py` の `render()` と同じ形で、`__mailboxd_mailboxes` に架空の 2 件（`alice@example.com` と `bob@example.com`、パスワードは `alice-password` と `bob-password`、トークンは `alice-token` と `bob-token`）を、`mailboxd_trusted_authserv_id` に空文字を渡して描画する。

```python
def test_every_token_is_limited_to_its_own_mailbox(self):
    tokens = yaml.safe_load(render("config.yaml.j2"))["auth"]["tokens"]
    self.assertEqual([t["mailboxes"] for t in tokens], [["alice"], ["bob"]])
    for token in tokens:
        self.assertIsInstance(token, dict)
        self.assertEqual(token["scopes"], ["read", "draft", "organize"])

def test_sending_cannot_reach_a_server(self):
    config = yaml.safe_load(render("config.yaml.j2"))
    self.assertIs(config["send_guard"]["dry_run"], True)
    for mailbox in config["mailboxes"]:
        self.assertEqual(mailbox["smtp"]["host"], "smtp.invalid")
        self.assertNotIn("${", mailbox["smtp"]["password"])

def test_imap_points_at_sakura_over_tls(self):
    imap = yaml.safe_load(render("config.yaml.j2"))["mailboxes"][0]["imap"]
    self.assertEqual((imap["host"], imap["port"], imap["tls"]), ("rewse.sakura.ne.jp", 993, "ssl"))
    self.assertEqual(imap["password"], "${MAILBOXD_PASSWORD_ALICE}")

def test_config_holds_no_secret(self):
    text = render("config.yaml.j2")
    self.assertNotIn("alice-password", text)
    self.assertNotIn("alice-token", text)

def test_env_file_carries_the_secrets(self):
    lines = [line for line in render("env.j2").splitlines() if line and not line.startswith("#")]
    env = dict(line.split("=", 1) for line in lines)
    self.assertEqual(env["MAILBOXD_TOKEN_ALICE"], "alice-token")
    self.assertEqual(env["MAILBOXD_PASSWORD_BOB"], "bob-password")

def test_trusted_authserv_id_is_omitted_until_known(self):
    self.assertNotIn("trusted_authserv_id", yaml.safe_load(render("config.yaml.j2"))["auth"])
    config = yaml.safe_load(render("config.yaml.j2", mailboxd_trusted_authserv_id="mx.example.com"))
    self.assertEqual(config["auth"]["trusted_authserv_id"], "mx.example.com")

def test_env_file_is_root_only_and_recreates_the_container(self):
    task = task_named("config.yml", "config | Deploy environment file")
    self.assertEqual(task["ansible.builtin.template"]["mode"], "0600")
    self.assertEqual(task["notify"], "Recreate mailboxd")
    self.assertTrue(task["no_log"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_mailboxd.py -v`
Expected: FAIL（テンプレートがない）

- [ ] **Step 3: vars、config.yml、テンプレート、ハンドラーを書く**

config.yml のタスクは次の順にする。`config | Resolve mailboxes`（`set_fact`、`no_log`）、`config | Create compose directory`（`/etc/compose/mailboxd`、`"0755"`）、`config | Create data directory`（`/srv/mailboxd`、owner と group は 10001、`"0750"`）、`config | Deploy configuration file`（`/etc/compose/mailboxd/config.yaml`、`"0644"`、notify `Recreate mailboxd`）、`config | Deploy environment file`（`/etc/compose/mailboxd/.env`、root、`"0600"`、`no_log`、notify `Recreate mailboxd`）。`config.yaml` の `smtp` には、下書きの差出人のためだけに置き、送れない値にしている理由をコメントで書く。`labels`、`watch`、`limits` は書かず、上流の既定値に任せる。

- [ ] **Step 4: テストが通ることを確かめる**

Run: Step 2 と同じ
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add roles/mailboxd tests/test_mailboxd.py
git commit -m "feat(mailboxd): render the mailbox and token configuration"
```

### Task 3: container コンポーネント

**Files:**
- Create: `roles/mailboxd/tasks/container.yml`、`roles/mailboxd/templates/compose.yaml.j2`
- Modify: `roles/mailboxd/tasks/main.yml`
- Test: `tests/test_mailboxd.py`

**Interfaces:**
- Consumes: Task 2 の `mailboxd_port`、`mailboxd_data_dir`、ハンドラー `Recreate mailboxd`、`render()`、`task_named()`
- Produces: `set_fact` `__mailboxd_image`（`.ref` が `tag@digest`）、Compose プロジェクト名 `mailboxd`、サービス名とコンテナ名 `mailboxd`。タグ `mailboxd_container` と `update`。テスト用の関数 `compose()`（`__mailboxd_image={"ref": "psyb0t/mailbox:v0.8.0@sha256:0"}` で描画して読む）と `main_imports()`（`tasks/main.yml` の import ごとのタグを返す）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_container_listens_on_loopback_only(self):
    self.assertEqual(compose()["services"]["mailboxd"]["ports"], ["127.0.0.1:8083:8000"])

def test_container_keeps_the_upstream_hardening(self):
    service = compose()["services"]["mailboxd"]
    self.assertIs(service["read_only"], True)
    self.assertEqual(service["cap_drop"], ["ALL"])
    self.assertIn("no-new-privileges:true", service["security_opt"])
    self.assertIn("healthcheck", service)

def test_container_reads_secrets_from_the_env_file_only(self):
    service = compose()["services"]["mailboxd"]
    self.assertEqual(service["env_file"], [".env"])
    self.assertIn("/etc/compose/mailboxd/config.yaml:/etc/mailboxd/config.yaml:ro", service["volumes"])
    self.assertIn("/srv/mailboxd:/var/lib/mailboxd", service["volumes"])

def test_no_watcher_is_deployed(self):
    self.assertEqual(list(compose()["services"]), ["mailboxd"])

def test_image_is_an_aged_release_tag(self):
    task = task_named("container.yml", "container | Resolve aged image")
    expression = task["ansible.builtin.set_fact"]["__mailboxd_image"]
    self.assertIn("oci:psyb0t/mailbox", expression)
    self.assertIn(r"^v\d+\.\d+\.\d+$", expression)

def test_container_component_is_an_update(self):
    self.assertEqual(main_imports()["container.yml"], ["mailboxd_container", "update"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_mailboxd.py -v`
Expected: 新しいテストが FAIL

- [ ] **Step 3: container.yml と compose.yaml.j2 を書き、main.yml に import を足す**

`roles/filebrowser/tasks/container.yml` と同じ流れ（Resolve aged image、Deploy compose file、check mode の報告、Start container）にする。`platform` は filebrowser と同じ式で選ぶ。Start container は `wait: true`、`wait_timeout: 120`。compose は上流の `docker-compose.yml` の `x-runtime` から `deploy`、`build`、`networks` を除いたものを `mailboxd` サービスに直接書き、`environment` に `WORKERS: 2`、`MAILBOXD_CONFIG`、`MAILBOXD_STATE_PATH` を置く。Deploy compose file の notify は `Recreate mailboxd`。

- [ ] **Step 4: テストが通ることを確かめる**

Run: Step 2 と同じ
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add roles/mailboxd tests/test_mailboxd.py
git commit -m "feat(mailboxd): run docker-mailbox under Compose"
```

### Task 4: apache と fail2ban コンポーネント、playbook

**Files:**
- Create: `roles/mailboxd/tasks/apache.yml`、`roles/mailboxd/tasks/fail2ban.yml`、`roles/mailboxd/meta/main.yml`、`roles/mailboxd/templates/mail-mcp.rewse.jp.conf.j2`、`roles/mailboxd/templates/fail2ban-filter.conf.j2`、`roles/mailboxd/templates/fail2ban-jail.conf.j2`
- Modify: `roles/mailboxd/tasks/main.yml`、`roles/mailboxd/handlers/main.yml`、`home-primary.yml`（`litellm` と `matterjs_server` の間に `mailboxd`、タグ `mailboxd`）、`tests/test_fail2ban_apache.py`（`JailActionTest` の一覧の `litellm` の後に `mailboxd`）
- Test: `tests/test_mailboxd.py`

**Interfaces:**
- Consumes: `mailboxd_hostname`、`mailboxd_port`、`render()`
- Produces: ジェイル名とフィルタ名 `mailboxd`、ハンドラー `Reload Apache` と `Restart fail2ban`（zabbix_mcp と同じ名前と中身）。タグ `mailboxd_apache`、`mailboxd_fail2ban`。main.yml の順は config、container、apache、fail2ban

- [ ] **Step 1: 失敗するテストを書く**

`access_line()`、`matches()`、`jail_section()` は `tests/test_zabbix_mcp.py` の同名の関数と同じ形にする。

```python
def test_vhost_proxies_to_loopback_and_streams(self):
    vhost = render("mail-mcp.rewse.jp.conf.j2")
    self.assertIn("ServerName mail-mcp.rewse.jp", vhost)
    self.assertIn("ProxyPass / http://127.0.0.1:8083/ flushpackets=on", vhost)
    self.assertIn("ProxyPreserveHost on", vhost)
    self.assertNotIn("Require ip", vhost)

def test_filter_matches_rejected_mcp_calls(self):
    self.assertTrue(matches(access_line(HOSTNAME, "POST /mcp", 401)))
    self.assertTrue(matches(access_line(HOSTNAME, "POST /mcp/", 401)))

def test_filter_ignores_metadata_success_and_other_vhosts(self):
    self.assertFalse(matches(access_line(HOSTNAME, "GET /.well-known/oauth-protected-resource", 401)))
    self.assertFalse(matches(access_line(HOSTNAME, "POST /mcp", 200)))
    self.assertFalse(matches(access_line(HOSTNAME, "GET /health", 200)))
    self.assertFalse(matches(access_line("zabbix-mcp.rewse.jp", "POST /mcp", 401)))

def test_jail_reads_the_vhost_log(self):
    jail = jail_section()
    self.assertEqual(jail["backend"], "auto")
    self.assertEqual(jail["filter"], "mailboxd")
    self.assertEqual(jail["logpath"], "/var/log/apache2/other_vhosts_access.log")

def test_role_depends_on_fail2ban_and_httpd(self):
    meta = yaml.safe_load((ROLE / "meta" / "main.yml").read_text())
    self.assertEqual([d["role"] for d in meta["dependencies"]], ["fail2ban", "httpd"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_mailboxd.py tests/test_fail2ban_apache.py -v`
Expected: 新しいテストと `JailActionTest` が FAIL

- [ ] **Step 3: タスク、テンプレート、meta、playbook を書く**

`roles/zabbix_mcp` の apache.yml、fail2ban.yml、各テンプレートを写し、名前を `mailboxd` と `mailboxd_hostname` に替え、vhost の `<Location />` を除く。vhost には、Muse の接続元がわからないので IP で絞らず、トークンと fail2ban と WAF で守る旨のコメントを書く。

- [ ] **Step 4: テストと lint を通す**

Run: `git add roles/mailboxd tests home-primary.yml && uv run --with pytest --with ansible-core pytest tests && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて PASS

- [ ] **Step 5: コミット**

```bash
git add roles/mailboxd tests home-primary.yml
git commit -m "feat(mailboxd): publish mail-mcp.rewse.jp through Apache with fail2ban"
```

### Task 5: fox に入れて家から確かめる（段階 1）

**Interfaces:**
- Consumes: Task 1 から 4 のロール
- Produces: fox で動く mailboxd。`mailboxd_trusted_authserv_id` の値

- [ ] **Step 1: check モードで流す**

Run: `git pull` のあと `ansible-playbook home-primary.yml --tags mailboxd --check --diff`
Expected: 失敗がない

- [ ] **Step 2: 適用し、2 回目が changed=0 になることを確かめる**

Run: 同じコマンドを `--check` なしで 2 回
Expected: 終了コード 0、2 回目は `changed=0`

- [ ] **Step 3: 家から HTTP の振る舞いを確かめる**

`curl --resolve mail-mcp.rewse.jp:443:192.168.0.30` で次を確かめる。トークンは `op read` から変数に入れ、端末に出さない。
- `GET /health` が 200
- トークンなしの `POST /mcp` が 401（BAN を避けるため 5 回未満にとどめる）
- 利用者のトークンで MCP の `initialize` と `tools/list` が通り、一覧に `send` と `send_draft` がなく、`delete_message` に `permanent` 引数がない
- `tools/call` で、ほかの家族のメールボックスを名前とアドレスの両方で指定すると拒否される
- `tools/call` で `reply` を `draft=false` で、`delete_message` を `permanent=true` で直接呼ぶと拒否される

- [ ] **Step 4: `trusted_authserv_id` を決める**

利用者のメールボックスの新しいメールを `get_message` の `headers=true` で読み、Sakura が付けた `Authentication-Results` の authserv-id を `mailboxd_trusted_authserv_id` に入れる。`--tags mailboxd_config` で適用し、同じメールの判定が `trusted: true` になることを確かめる。

- [ ] **Step 5: コミット**

```bash
git add roles/mailboxd/vars/main.yml
git commit -m "feat(mailboxd): trust the authentication results that Sakura stamps"
```

### Task 6: 一時トンネルで Muse から確かめる（段階 2）

利用者とのやり取りが要る。リポジトリは変えない。

- [ ] **Step 1: 利用者にテストメールを送ってもらう**

件名に「mailboxd テスト」を含むメールを、利用者が自分のアドレスに送る。

- [ ] **Step 2: fox で Quick Tunnel を起動する**

4 日以上前に出た `cloudflare/cloudflared` のタグをダイジェストで固定し、fox で `docker run -d --rm --name mailboxd-tunnel --network host <image@digest> tunnel --no-autoupdate --url http://127.0.0.1:8083` を実行する。`docker logs mailboxd-tunnel` に出る `*.trycloudflare.com` の名前を控える。

- [ ] **Step 3: 利用者に Muse でコネクタを作ってもらう**

spec の付録のプロンプトに、トンネルの名前と利用者のメールボックス名を入れて渡す。トークンは利用者が 1Password から Muse の入力欄に入れる。

- [ ] **Step 4: 結果を受け取る**

Expected: 付録の 1 から 6 が成功し、7 で送信と完全削除が拒否される。`audit_log` を見られるトークンはないので、fox の `docker logs mailboxd` に利用者のトークン名で操作が残ることを見る

- [ ] **Step 5: トンネルを止める**

Run: fox で `docker stop mailboxd-tunnel` のあと `docker ps -a --filter name=mailboxd-tunnel`
Expected: 何も出ない

通らなければここで止め、spec の「残るリスク」を利用者と相談する。

### Task 7: CloudFront、UniFi、security-agent（段階 3）

**Files:**
- Modify（`~/git/cloudfront-waf`）: `infra/template.yaml`、`scripts/switch-dns.sh`、`tests/test_template.py`、`tests/test_switch_dns.py`、`README.md`、`docs/setup.md`
- Modify（`~/git/security-agent`）: `targets.toml`、`infra/template.yaml`、`tests/test_config.py`、`tests/test_infra.py`、`docs/setup.md`

- [ ] **Step 1: cloudfront-waf に名前を足す**

`git pull` のあと、`72b9c81 feat: serve expense.rewse.jp through CloudFront` と同じ箇所に `mail-mcp` を足す（公開名は 13 個、サブドメインは 12 個になる）。README の `BlockManagedRules` の段落に、`mail-mcp.rewse.jp` への Muse の MCP 呼び出しも誤検知を確かめる対象に含める旨を足す。テストと pre-commit を通してコミットし、push する。

- [ ] **Step 2: スタックをデプロイし、公開 DNS を切り替える**

Run: cloudfront-waf で `AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` のあと `AWS_PROFILE=cloudfront-waf-deploy scripts/switch-dns.sh cloudfront`。`cloudfront-waf-deploy` は `tats` が引き受けるロールなので、自宅の Mac から実行できる
Expected: スタックの更新が完了し、`curl 'https://dns.google/resolve?name=mail-mcp.rewse.jp&type=CNAME'` が CloudFront の名前を返す

- [ ] **Step 3: UniFi に DNS ポリシーを足す**

メモリ `rewse-jp-hostname-routing` の手順で、`mail-mcp.rewse.jp` を `fox.rewse.jp` に向ける `CNAME_RECORD`（`ttlSeconds: 0`）を POST する。
Expected: 家から `dig mail-mcp.rewse.jp` が fox の内部アドレスに解決する

- [ ] **Step 4: CloudFront 経由で確かめる**

`curl --resolve mail-mcp.rewse.jp:443:<hass.rewse.jp のエッジの IP>` で `/health` が 200、トークンなしの `POST /mcp` が 401 を返すことを見る。利用者に Muse のコネクタの URL を `https://mail-mcp.rewse.jp/mcp` に替えてもらい、付録の 1 から 7 をもう一度頼む。各家族の INBOX で、条件なしの `search` が 60 秒以内に返ることも確かめる。

- [ ] **Step 5: security-agent に毎月のペネトレーションテストを足す**

`git pull` のあと、`1b0a9c2 feat: add a monthly pentest for expense.rewse.jp` と同じ箇所に `mail-mcp.rewse.jp` を足す。開始日は使われていない 13 日、時刻は 21:15 UTC。サインインはせず、匿名で試す。テストを通してコミットし、push する。デプロイと対象ドメインの検証は `AWS_PROFILE=security-agent-deploy` で行い、手順は security-agent の `docs/setup.md` に従う。IAM のリソースを変えないので、このロールで足りる。

### Task 8: 家族のコネクタと後片付け（段階 4）

- [ ] **Step 1: 家族 2 人の Muse にコネクタを作る**

利用者が家族の Muse で、付録のプロンプト（URL は `https://mail-mcp.rewse.jp/mcp`、メールボックス名は本人のもの）を使う。トークンは本人の項目から入力する。
Expected: 付録の 1 から 7 が利用者のときと同じ結果になり、ほかの家族のメールボックスは見えない

- [ ] **Step 2: AGENTS.md の Subdomains の手順に漏れがないかを見直す**

chezmoi に変更がないことを確かめる。

- [ ] **Step 3: spec と plan をアーカイブする**

```bash
git mv docs/superpowers/specs/2026-11-02-mailboxd-mcp-design.md docs/superpowers/archive/specs/
git mv docs/superpowers/plans/2026-11-02-mailboxd-mcp.md docs/superpowers/archive/plans/
git commit -m "docs: archive the mailboxd MCP design and plan"
```
