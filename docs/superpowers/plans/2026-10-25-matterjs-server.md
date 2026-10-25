# matterjs-server への移行と matter.rewse.jp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox の python-matter-server を新ロール `matterjs_server` の matterjs-server に置き換え、ダッシュボードを家と VPN から `https://matter.rewse.jp/` で開けるようにする。

**Architecture:** matterjs-server は host ネットワークで `127.0.0.1,::1` の 5580 だけで待ち受け、HA は今と同じ `ws://localhost:5580/ws` を使う。ダッシュボードのためだけに Apache の vhost が TLS を終端し、`Require ip` で家と VPN に絞る。データは手作業で `/srv/matterjs_server/data` にコピーし、ロールはデータがあるときだけ起動する。

**Tech Stack:** Ansible（community.docker.docker_compose_v2、aged_release）、Docker Compose、Apache（mod_proxy_http、mod_proxy_wstunnel）、sysctl、pytest（unittest、jinja2、PyYAML）、UniFi

**Spec:** `docs/superpowers/specs/2026-10-25-matterjs-server-design.md`

## Global Constraints

- ロール名は `matterjs_server`、Compose プロジェクトは `/etc/compose/matterjs_server/compose.yaml`（`name: matterjs_server`）、サービスとコンテナの名前は `matterjs-server`、データは `/srv/matterjs_server/data`（UID と GID 1000、`"0700"`）
- イメージは `aged_release` の `oci:ghcr.io/matter-js/matterjs-server`、`pattern='^\d+\.\d+\.\d+$'`、プラットフォームの選び方は今の `roles/matter_server/tasks/container.yml` と同じ
- 環境変数は `LISTEN_ADDRESS=127.0.0.1,::1`、`PRIMARY_INTERFACE=eth0`、`PRODUCTION_MODE=true` の 3 つ。`/run/dbus`、`apparmor:unconfined`、`NOBLE_BINDINGS`、`BLUETOOTH_ADAPTER`、`cap_add` は持たない
- sysctl は `net.ipv4.ping_group_range = 0 2147483647`
- vhost のホスト名は `matter.rewse.jp`、プロキシ先は `ws://127.0.0.1:5580/ws`（先）と `http://127.0.0.1:5580/`（後）
- vhost が許可する接続元は `127.0.0.1`、`::1`、`networks` の `home_private_ipv4`、`home_private_ipv6`、`home_public_ipv4`、`home_public_ipv6`、`aws_private_ipv4`、`aws_public_ipv6` だけ。`office_public_ipv4` は入れない
- 証明書は `/etc/letsencrypt/live/rewse.jp/fullchain.pem` と `privkey.pem`、`Include /etc/letsencrypt/options-ssl-apache.conf`
- fail2ban、CloudFront、公開 DNS、security-agent、chezmoi は変えない
- `/srv/matter_server` には一切触れない
- 対象ホストは fox だけで、プレイブックは `home-primary.yml`
- AGENTS.md の Ansible の規約に従う。zabbix_mcp と filebrowser が見本で、タスク名は `<component> | ...`、テンプレートの先頭は `{{ ansible_managed | comment }}`（YAML なら `---` の後）、`mode` は 4 桁の文字列、`command` には理由のコメントと `changed_when`、`debug` には `verbosity` を付ける
- コメントは英語で、今のコードについて書く。変更の経緯はコミットメッセージに書く
- check mode は非破壊で失敗しない。2 回目の実行は `changed=0`
- コミットメッセージは Conventional Commits。push の前に `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests` を通す。新しいファイルは先に stage する
- main への push、UniFi への書き込み、fox での手作業と反映、鍵の操作は、それぞれ実施の前にユーザーの確認を取る
- 反映の前に `git -P fetch && git -P log --oneline HEAD..origin/main` で取り込み漏れがないことを確かめる
- 120 秒を超える ansible-playbook は `nohup sh -c '... > LOG 2>&1; echo EXIT=$? >> LOG' > /dev/null 2>&1 &` で走らせ、`EXIT=` の行で終了コードを確かめる

## Review Focus

- 空のデータディレクトリで一度でも起動すると、Python 版のデータが二度と取り込まれない。`chip.json` も `server/` もないときに起動タスクが走らず、通常の実行では fail、check mode では debug になることを Task 2 のテストで固定する
- HA の `localhost` が `::1` に解決されると、IPv4 だけで待ち受けていればつながらない。`LISTEN_ADDRESS` がちょうど `127.0.0.1,::1` であることを Task 2 のテストで固定する
- `/ws` の `ProxyPass` が `/` より後にあると、WebSocket が http で転送されてダッシュボードが動かない。順序を Task 3 のテストで固定する
- 家の端末は IPv6 の公開アドレスから来る。`Require ip` の一覧が過不足なく一致し、`Require all granted` と `office_public_ipv4` がないことを Task 3 のテストで固定する
- 旧構成の撤去がデータまで消すと、ロールバックできなくなる。撤去タスクの対象が `/etc/compose/matter_server` だけで、`/srv/matter_server` を含まないことを Task 2 のテストで固定する

---

### Task 1: matterjs_server ロールの骨組みと sysctl

**Files:**
- Create: `roles/matterjs_server/tasks/main.yml`
- Create: `roles/matterjs_server/tasks/sysctl.yml`
- Create: `roles/matterjs_server/files/60-matterjs-server-ping.conf`
- Create: `roles/matterjs_server/handlers/main.yml`
- Create: `roles/matterjs_server/meta/main.yml`
- Create: `roles/matterjs_server/vars/main.yml`
- Test: `tests/test_matterjs_server.py`（実行ビットを付ける。ruff EXE001）

**Interfaces:**
- Produces: 変数 `matterjs_server_hostname: matter.rewse.jp`、`matterjs_server_port: 5580`、`matterjs_server_listen_address: "127.0.0.1,::1"`、`matterjs_server_primary_interface: eth0`、`matterjs_server_data_dir: /srv/matterjs_server/data`
- Produces: ハンドラー `Reload sysctl`（`roles/raspberrypi/handlers/main.yml` と同じ名前と中身）。Task 3 が `Reload Apache` を足す
- Produces: テストの補助 `ROLE`、`REPO_ROOT`、`NETWORKS`（`tests/test_zabbix_mcp.py` と同じ 7 キーの偽の値）、`role_vars() -> dict`、`load_tasks(name: str) -> list[dict]`（`tasks/<name>` を `yaml.safe_load`）、`render(name: str, **overrides) -> str`。`render` は `tests/test_zabbix_mcp.py` と同じ jinja2 の環境（`StrictUndefined`、`comment`）で、`vars/main.yml` の値、`ansible_managed`、`networks=NETWORKS`、`__matterjs_server_image={"ref": "ghcr.io/matter-js/matterjs-server:1.5.5@sha256:" + "0" * 64}` で描画する。Task 2 と Task 3 も使う

- [ ] **Step 1: 失敗するテストを書く**

`MatterjsServerRoleTest` に次を書く。

```python
    def test_ping_is_open_to_every_group(self):
        conf = (ROLE / "files" / "60-matterjs-server-ping.conf").read_text()
        self.assertRegex(conf, r"(?m)^net\.ipv4\.ping_group_range = 0 2147483647$")

    def test_sysctl_reload_matches_the_raspberrypi_role(self):
        mine = {h["name"]: h for h in yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())}
        theirs = {h["name"]: h for h in yaml.safe_load(
            (REPO_ROOT / "roles" / "raspberrypi" / "handlers" / "main.yml").read_text())}
        self.assertEqual(mine["Reload sysctl"], theirs["Reload sysctl"])

    def test_sysctl_drop_in_notifies_the_reload(self):
        task = load_tasks("sysctl.yml")[0]
        self.assertEqual(task["ansible.builtin.copy"]["dest"], "/etc/sysctl.d")
        self.assertEqual(task["notify"], "Reload sysctl")

    def test_sysctl_is_the_first_component(self):
        first = load_tasks("main.yml")[0]
        self.assertEqual(first["ansible.builtin.import_tasks"], "sysctl.yml")
        self.assertEqual(first["tags"], ["matterjs_server_sysctl"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: FAIL（`roles/matterjs_server` がない）

- [ ] **Step 3: ロールを作る**

`vars/main.yml` に Interfaces の 5 変数を置く。`meta/main.yml` は `docker` と `httpd` をそれぞれ同名のタグ付きで依存にする。`tasks/main.yml` はこの時点では sysctl だけを import する。`sysctl.yml` は `sysctl | Allow unprivileged ping` で `files/60-matterjs-server-ping.conf` を `/etc/sysctl.d` に `"0644"` で置く。ドロップインには、コンテナが UID 1000 で ping コマンドを使いノードの到達を確かめること、許可されるのは ICMP echo だけであることをコメントで書く。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add roles/matterjs_server tests/test_matterjs_server.py
git commit -m "feat(matterjs_server): add the role with an unprivileged ping sysctl"
```

### Task 2: container コンポーネント

**Files:**
- Create: `roles/matterjs_server/tasks/container.yml`
- Create: `roles/matterjs_server/templates/compose.yaml.j2`
- Modify: `roles/matterjs_server/tasks/main.yml`
- Test: `tests/test_matterjs_server.py`

**Interfaces:**
- Consumes: Task 1 の変数、`render`、`load_tasks`
- Produces: `set_fact` の `__matterjs_server_image`（`aged_release` の結果。compose は `.ref` を使う）、`register` の `__matterjs_server_storage`、`__matterjs_server_chip`、`__matterjs_server_compose`、`__matterjs_server_legacy`

- [ ] **Step 1: 失敗するテストを書く**

`MatterjsServerContainerTest` に次を書く。`compose()` は `yaml.safe_load(render("compose.yaml.j2"))["services"]["matterjs-server"]` を返すモジュールの補助とする。

```python
    def test_compose_project_and_service(self):
        project = yaml.safe_load(render("compose.yaml.j2"))
        self.assertEqual(project["name"], "matterjs_server")
        service = project["services"]["matterjs-server"]
        self.assertEqual(service["container_name"], "matterjs-server")
        self.assertEqual(service["network_mode"], "host")
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(service["volumes"], ["/srv/matterjs_server/data:/data"])
        self.assertTrue(service["image"].startswith("ghcr.io/matter-js/matterjs-server:"))

    def test_environment_is_exactly_the_three_settings(self):
        self.assertEqual(compose()["environment"], {
            "LISTEN_ADDRESS": "127.0.0.1,::1",
            "PRIMARY_INTERFACE": "eth0",
            "PRODUCTION_MODE": "true",
        })

    def test_no_bluetooth_or_extra_privileges(self):
        service = compose()
        for key in ("security_opt", "cap_add", "privileged", "user"):
            self.assertNotIn(key, service)
        self.assertNotIn("/run/dbus", render("compose.yaml.j2"))

    def test_start_is_guarded_by_migrated_or_python_data(self):
        tasks = {t["name"]: t for t in load_tasks("container.yml")}
        stats = {t["ansible.builtin.stat"]["path"] for t in tasks.values() if "ansible.builtin.stat" in t}
        self.assertLessEqual(
            {"{{ matterjs_server_data_dir }}/chip.json", "{{ matterjs_server_data_dir }}/server"}, stats)
        fail = tasks["container | Fail without data to migrate"]
        report = tasks["container | Report skipped start without data"]
        start = tasks["container | Start containers"]
        self.assertIn("not ansible_check_mode", str(fail["when"]))
        self.assertIn("ansible_check_mode", str(report["when"]))
        self.assertIn("__matterjs_server_chip.stat.exists", str(start["when"]))
        self.assertIn("__matterjs_server_storage.stat.exists", str(start["when"]))

    def test_data_directory_is_owned_by_the_container_user(self):
        task = next(t["ansible.builtin.file"] for t in load_tasks("container.yml")
                    if t.get("ansible.builtin.file", {}).get("path") == "{{ matterjs_server_data_dir }}")
        self.assertEqual((task["owner"], task["group"], task["mode"]), (1000, 1000, "0700"))
        self.assertNotIn("recurse", task)

    def test_legacy_removal_keeps_python_data(self):
        self.assertNotIn("/srv/matter_server", (ROLE / "tasks" / "container.yml").read_text())
        tasks = load_tasks("container.yml")
        removed = [t["ansible.builtin.file"]["path"] for t in tasks
                   if t.get("ansible.builtin.file", {}).get("state") == "absent"]
        self.assertEqual(removed, ["/etc/compose/matter_server"])
        down = next(t["community.docker.docker_compose_v2"] for t in tasks
                    if t.get("community.docker.docker_compose_v2", {}).get("state") == "absent")
        self.assertEqual(down["project_src"], "/etc/compose/matter_server")

    def test_container_is_an_update_component(self):
        imports = {t["ansible.builtin.import_tasks"]: t["tags"] for t in load_tasks("main.yml")}
        self.assertEqual(imports["container.yml"], ["matterjs_server_container", "update"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: FAIL（`compose.yaml.j2` と `container.yml` がない）

- [ ] **Step 3: container コンポーネントを書く**

`container.yml` のタスクは次の順に並べる。

1. `container | Resolve aged image`: `roles/matter_server/tasks/container.yml` と同じ形で `oci:ghcr.io/matter-js/matterjs-server` を解決する
2. `container | Create data directory`: `"{{ matterjs_server_data_dir }}"` を `owner: 1000`、`group: 1000`（数値）、`mode: "0700"` で作る。再帰しない
3. `container | Check migrated data` と `container | Check Python data`: `{{ matterjs_server_data_dir }}/server` と `{{ matterjs_server_data_dir }}/chip.json` を stat し、`__matterjs_server_storage` と `__matterjs_server_chip` に入れる
4. `container | Fail without data to migrate`: どちらもなく check mode でないとき。メッセージは、Python 版の `chip.json` と `<n>.json` をコピーしてから実行するように、という趣旨にする。コメントには、空のディレクトリで一度起動すると Python 版のデータが取り込まれなくなることを書く
5. `container | Report skipped start without data`: どちらもなく check mode のとき。`verbosity: 0`
6. `container | Create compose directory`、`container | Deploy compose file`（`__matterjs_server_compose`）、`container | Report skipped start in check mode`、`container | Start containers`: `roles/matter_server/tasks/container.yml` と同じ形で、パスを `/etc/compose/matterjs_server` にする。`Start containers` の `when` は、元の条件と「`__matterjs_server_chip.stat.exists or __matterjs_server_storage.stat.exists`」のリストにする
7. `container | Check legacy compose project`: `/etc/compose/matter_server/compose.yaml` を stat して `__matterjs_server_legacy` に入れる
8. `container | Remove legacy compose project`: あるときに `docker_compose_v2` で `project_src: /etc/compose/matter_server`、`state: absent`
9. `container | Remove legacy compose directory`: `/etc/compose/matter_server` を `state: absent`

`compose.yaml.j2` は `roles/matter_server/templates/compose.yaml.j2` を元に、Constraints の名前、イメージ、ボリューム、環境変数（`matterjs_server_listen_address`、`matterjs_server_primary_interface`、`PRODUCTION_MODE` は `"true"` の文字列）にする。`PRODUCTION_MODE` には、ダッシュボードを Apache の裏で出すためのものだとコメントを付ける。`tasks/main.yml` に container の import をタグ `matterjs_server_container` と `update` で足す。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add roles/matterjs_server tests/test_matterjs_server.py
git commit -m "feat(matterjs_server): run matterjs-server on loopback once data is in place"
```

### Task 3: apache コンポーネント

**Files:**
- Create: `roles/matterjs_server/tasks/apache.yml`
- Create: `roles/matterjs_server/templates/matter.rewse.jp.conf.j2`
- Modify: `roles/matterjs_server/tasks/main.yml`
- Modify: `roles/matterjs_server/handlers/main.yml`
- Test: `tests/test_matterjs_server.py`

**Interfaces:**
- Consumes: Task 1 の `matterjs_server_hostname`、`matterjs_server_port`、`render`、`load_tasks`、`NETWORKS`
- Produces: ハンドラー `Reload Apache`（`roles/httpd/handlers/main.yml` と同じ中身）、`register` の `__matterjs_server_a2ensite`

- [ ] **Step 1: 失敗するテストを書く**

`MatterjsServerApacheTest` に次を書く。

```python
    def test_websocket_is_proxied_before_the_dashboard(self):
        vhost = render("matter.rewse.jp.conf.j2")
        self.assertIn("ServerName matter.rewse.jp", vhost)
        self.assertLess(vhost.index("ProxyPass /ws ws://127.0.0.1:5580/ws"),
                        vhost.index("ProxyPass / http://127.0.0.1:5580/"))

    def test_only_home_and_vpn_may_connect(self):
        vhost = render("matter.rewse.jp.conf.j2")
        allowed = re.findall(r"(?m)^\s*Require ip (\S+)$", vhost)
        self.assertEqual(sorted(allowed), sorted([
            "127.0.0.1", "::1",
            NETWORKS["home_private_ipv4"], NETWORKS["home_private_ipv6"],
            NETWORKS["home_public_ipv4"], NETWORKS["home_public_ipv6"],
            NETWORKS["aws_private_ipv4"], NETWORKS["aws_public_ipv6"],
        ]))
        self.assertNotIn("Require all granted", vhost)
        for office in NETWORKS["office_public_ipv4"]:
            self.assertNotIn(office, vhost)

    def test_vhost_uses_the_wildcard_certificate(self):
        vhost = render("matter.rewse.jp.conf.j2")
        self.assertIn("SSLCertificateFile /etc/letsencrypt/live/rewse.jp/fullchain.pem", vhost)
        self.assertIn("SSLCertificateKeyFile /etc/letsencrypt/live/rewse.jp/privkey.pem", vhost)

    def test_apache_reload_matches_the_httpd_role(self):
        mine = {h["name"]: h for h in yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())}
        theirs = {h["name"]: h for h in yaml.safe_load(
            (REPO_ROOT / "roles" / "httpd" / "handlers" / "main.yml").read_text())}
        self.assertEqual(mine["Reload Apache"], theirs["Reload Apache"])

    def test_components_and_dependencies(self):
        imports = [t["ansible.builtin.import_tasks"] for t in load_tasks("main.yml")]
        self.assertEqual(imports, ["sysctl.yml", "container.yml", "apache.yml"])
        deps = [d["role"] for d in yaml.safe_load((ROLE / "meta" / "main.yml").read_text())["dependencies"]]
        self.assertEqual(deps, ["docker", "httpd"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: FAIL（vhost のテンプレートがない）

- [ ] **Step 3: vhost とタスクを書く**

`roles/zabbix_mcp/templates/zabbix-mcp.rewse.jp.conf.j2` と `roles/zabbix_mcp/tasks/apache.yml` を元にする。`ProxyPreserveHost` と `flushpackets` は使わず、teslamate の vhost と同じく `/ws` の `ProxyPass` と `ProxyPassReverse` を `/` の前に置く。`Require ip` は Constraints の 8 つにする。コメントには、Matter を使うだけなら HA が `localhost` に直接つなぐこと、この vhost はダッシュボードのためにあり、ダッシュボードはログインなしでノードの削除や ACL の書き換えができるので家と VPN に絞ることを書く。`handlers/main.yml` に `Reload Apache` を `Reload sysctl` の前に足す（アルファベット順）。`tasks/main.yml` に apache の import をタグ `matterjs_server_apache` で足す。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add roles/matterjs_server tests/test_matterjs_server.py
git commit -m "feat(matterjs_server): serve the dashboard at matter.rewse.jp to home and the VPN"
```

### Task 4: matter_server を matterjs_server に置き換える

**Files:**
- Modify: `home-primary.yml:52-54`
- Modify: `roles/homeassistant/meta/main.yml:12-14`
- Delete: `roles/matter_server/`
- Test: `tests/test_matterjs_server.py`

**Interfaces:**
- Consumes: Task 1 から 3 のロール

- [ ] **Step 1: 失敗するテストを書く**

`MatterjsServerWiringTest` に次を書く。

```python
    def test_home_primary_runs_matterjs_server(self):
        roles = [r["role"] for r in yaml.safe_load((REPO_ROOT / "home-primary.yml").read_text())[0]["roles"]]
        self.assertIn("matterjs_server", roles)
        self.assertNotIn("matter_server", roles)

    def test_homeassistant_depends_on_matterjs_server(self):
        deps = [d["role"] for d in yaml.safe_load(
            (REPO_ROOT / "roles" / "homeassistant" / "meta" / "main.yml").read_text())["dependencies"]]
        self.assertIn("matterjs_server", deps)
        self.assertNotIn("matter_server", deps)

    def test_python_matter_server_role_is_gone(self):
        self.assertFalse((REPO_ROOT / "roles" / "matter_server").exists())
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_matterjs_server.py -v`
Expected: FAIL（3 つとも）

- [ ] **Step 3: 置き換える**

`home-primary.yml` と `roles/homeassistant/meta/main.yml` の `matter_server`（ロール名とタグ）を `matterjs_server` にする。playbook では litellm と mhz19 の間のままでアルファベット順が保たれる。`git rm -r roles/matter_server` で旧ロールを消す。

- [ ] **Step 4: 全体を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests`
Expected: 全件 PASS

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: 全フック Passed。フックが直したファイルがあれば stage して再実行する

- [ ] **Step 5: コミット**

```bash
git add home-primary.yml roles/homeassistant/meta/main.yml tests/test_matterjs_server.py
git commit -m "feat(matterjs_server): replace the archived python-matter-server"
```

### Task 5: 切り替え

ここから先は fox と UniFi への書き込みになる。各ステップの前にユーザーの確認を取る。

- [ ] **Step 1: push する**

ユーザーの確認後に `git -P push`。

- [ ] **Step 2: UniFi の DNS ポリシーを足す**

zabbix-mcp と同じく Site Manager API（コンソール `sierra`、キーは `op://ansible/bvdayezevkxx6kmhjc3kmug7u4/credential`）で、`matter.rewse.jp` を `fox.rewse.jp` への CNAME、`ttlSeconds: 0` で足す。
確認: `dig +short matter.rewse.jp` が `fox.rewse.jp.` と `192.168.0.30` を返す。

- [ ] **Step 3: check mode で差分を見る**

Run: `git -P fetch && git -P log --oneline HEAD..origin/main`（空であること）
Run: `direnv exec . ansible-playbook home-primary.yml --tags matterjs_server --check --diff`
Expected: 終了コード 0。sysctl のドロップイン、compose、vhost の差分と、`Report skipped start without data` が出る。旧 compose の撤去は changed になる。docker と httpd に差分がない

- [ ] **Step 4: 旧サーバーを止めてデータを置く**

```bash
ssh fox 'sudo docker compose -f /etc/compose/matter_server/compose.yaml stop'
ssh fox 'sudo install -d -o 1000 -g 1000 -m 0700 /srv/matterjs_server/data && sudo install -o 1000 -g 1000 -m 0600 /srv/matter_server/data/chip.json /srv/matter_server/data/9812021715157225473.json /srv/matterjs_server/data/'
ssh fox 'sudo ls -la /srv/matterjs_server/data'
```

Expected: `matter-server` が Exited になり、新しいディレクトリには 2 ファイルだけが UID 1000 で入っている。ここから HA の Matter のエンティティは使えなくなる。

- [ ] **Step 5: 反映する**

Run: `direnv exec . ansible-playbook home-primary.yml --tags matterjs_server --diff`
Expected: 終了コード 0、`matterjs-server` が起動し、`/etc/compose/matter_server` がなくなる

- [ ] **Step 6: 移行と待ち受けを確かめる**

```bash
ssh fox 'sudo docker logs matterjs-server 2>&1 | tail -100'
ssh fox "sudo docker inspect --format '{{.State.Health.Status}}' matterjs-server"
ssh fox 'sudo ss -ltnp | grep 5580'
ssh fox 'sysctl net.ipv4.ping_group_range && sudo docker exec matterjs-server ping -c 1 192.168.0.1'
nc -vz -w 3 192.168.0.30 5580
nc -6 -vz -w 3 240f:143:f60c:1:2ecf:67ff:fe0f:f65d 5580
```

Expected: ログに移行と 4 ノードのインタビューが出る（初回の「no addresses known」は無視する）。healthy になる。5580 は `127.0.0.1` と `[::1]` だけで待ち受ける。`0 2147483647` で ping が通る。Mac からの `nc` は 2 つとも失敗する。

- [ ] **Step 7: HA と鍵を確かめる**

mcporter の `home-assistant` で Matter のエンティティ（M2 配下のセンサーを含む）の state を引き、`unavailable` がないことを確かめる。鍵の施錠と解錠は、ユーザーに伝えてから行うか、ユーザーに操作してもらう。

- [ ] **Step 8: ダッシュボードを確かめる**

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://matter.rewse.jp/
curl -sS -o /dev/null -w '%{http_code}\n' --http1.1 --max-time 3 -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" https://matter.rewse.jp/ws
ssh alfa "curl -sS -o /dev/null -w '%{http_code}\n' --resolve matter.rewse.jp:443:192.168.0.30 https://matter.rewse.jp/"
```

Expected: 家から 200 と 101、alfa（VPN 側）から 200。ユーザーにブラウザでダッシュボードを開いてもらい、ノードの一覧が出ることを確かめる。

- [ ] **Step 9: 冪等性を確かめる**

Run: `direnv exec . ansible-playbook home-primary.yml --tags matterjs_server --check --diff`
Expected: 終了コード 0、`changed=0`

失敗したときは spec の「戻し方」に従う。
