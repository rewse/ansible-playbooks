# calendar-mcp のコンテナを専用のホストアカウントで動かす 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** calendar-mcp のコンテナを、fox に登録した `calendar-mcp`（uid 980、gid 980）で動かし、データと設定ファイルもそのアカウントの所有にする。

**Architecture:** 新しいコンポーネント `user.yml` がホストにシステムグループとシステムユーザーを作る。compose の `user:` でイメージの mcpuser（999）を上書きし、config と container の各コンポーネントは番号で所有者を指定する。既存のデータファイルは、コンテナを作り直す前に再帰的に所有者を付け替える。

**Tech Stack:** Ansible（`ansible.builtin.group`、`ansible.builtin.user`、`ansible.builtin.file`）、Docker Compose、pytest（unittest 形式の契約テスト）

**Spec:** `docs/superpowers/archive/specs/2026-11-07-calendar-mcp-container-uid-design.md`

## Global Constraints

- アカウント名は `calendar-mcp`（グループ、ユーザーとも）
- `calendar_mcp_uid: 980`、`calendar_mcp_gid: 980`（`roles/calendar_mcp/vars/main.yml`）
- 新しいコンポーネントのタグは `calendar_mcp_user`。`tasks/main.yml` の先頭に import する
- データファイルの付け替えは `owner` と `group` だけで、`mode` を当てない
- fork の Dockerfile は変えない
- Task 1 と Task 2 の間で fox に適用しない（Task 1 だけでは所有者が 980 になり、コンテナは 999 のまま動く）
- ansible-playbook は同時に二つ走らせない
- テスト: `uv run --with pytest --with ansible-core pytest tests -q`
- リント: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`（新規ファイルは先に `git add` する）
- コミット前に `git -P status -sb` でブランチが `main` であることを確かめる。別のセッションが root clone を切り替えていたら、`.worktrees/<name>` の worktree で続ける

## Review Focus

- uid 980 か gid 980 を別のアカウントがすでに持っているホスト: user と group モジュールが失敗して止まる。Task 3 Step 2 で fox に先客がいないことを確かめる
- アカウントがまだない状態での初回 `--check`: 失敗せずに差分だけを出す。Task 3 Step 3 がこの状態で走る
- uid 999 が書いた既存の鍵（0600）とログ: 付け替え後に新しい実行ユーザーが読めて追記でき、DataProtection が鍵を作り直さない。Task 3 Step 6 で鍵の数とログの更新を見る
- データディレクトリ内にある root 所有の空ファイル `appsettings.json`（Docker が作ったバインドマウントの受け口）: 所有者が変わっても、読み取り専用のマウントで設定が読める。Task 3 Step 6 の `/health` 200 で確かめる
- 2 回目の実行: 再帰的な付け替えが `ok` になり、`changed=0` になる。Task 3 Step 7

---

### Task 1: ホストにアカウントを登録する

**Files:**
- Create: `roles/calendar_mcp/tasks/user.yml`
- Modify: `roles/calendar_mcp/tasks/main.yml`（先頭に import を足す）
- Modify: `roles/calendar_mcp/vars/main.yml:16-17`（`calendar_mcp_uid` とコメント）
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Produces: 変数 `calendar_mcp_uid`（980）と `calendar_mcp_gid`（980）。タスク名 `user | Create system group`（`ansible.builtin.group`）と `user | Create system user`（`ansible.builtin.user`）。テスト用の `ACCOUNT_IDS` と `resolved(expression) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`render_expression` の下に置く。

```python
# Distinct numbers, so a field that reads the other variable shows up.
ACCOUNT_IDS = {"calendar_mcp_uid": 1980, "calendar_mcp_gid": 1981}


def resolved(expression) -> str:
    """Render a task argument with the role vars and ACCOUNT_IDS."""
    return render_expression(str(expression), **(role_vars() | ACCOUNT_IDS))
```

`CalendarMcpComposeTest` の前に置く。

```python
class CalendarMcpUserTest(unittest.TestCase):
    def test_account_is_a_system_account_without_login(self):
        group = task_named("user.yml", "user | Create system group")[
            "ansible.builtin.group"
        ]
        user = task_named("user.yml", "user | Create system user")[
            "ansible.builtin.user"
        ]
        self.assertEqual(group["name"], "calendar-mcp")
        self.assertTrue(group["system"])
        self.assertEqual(resolved(group["gid"]), "1981")
        self.assertEqual(user["name"], "calendar-mcp")
        self.assertEqual(user["group"], "calendar-mcp")
        self.assertTrue(user["system"])
        self.assertEqual(resolved(user["uid"]), "1980")
        self.assertEqual(user["shell"], "/usr/sbin/nologin")
        self.assertFalse(user["create_home"])
```

`test_components_are_imported_in_order` の期待値を次にする。

```python
            ["user.yml", "config.yml", "container.yml", "apache.yml", "fail2ban.yml", "legacy.yml"],
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -q -k "system_account or imported_in_order"`
Expected: `test_account_is_a_system_account_without_login` が `FileNotFoundError`（`user.yml` がない）、`test_components_are_imported_in_order` が `Lists differ`（要素 0 が `'config.yml'` と `'user.yml'`）で失敗する

- [ ] **Step 3: 変数を変える**

`roles/calendar_mcp/vars/main.yml` の mcpuser のコメントと `calendar_mcp_uid: 999` を、次の内容に置き換える。コメントは英語で、イメージの mcpuser は 999 で、Ubuntu はこの番号を自分のシステムアカウントに割り当てる（fox では dnsmasq と systemd-journal）ため、ホストに `calendar-mcp` をこの番号で登録してコンテナをそのアカウントで動かす、と書く。

```yaml
calendar_mcp_uid: 980
calendar_mcp_gid: 980
```

- [ ] **Step 4: `roles/calendar_mcp/tasks/user.yml` を作る**

`roles/zabbix_mcp/tasks/user.yml` と同じ形で二つのタスクを置く。`user | Create system group` は `name: calendar-mcp`、`gid: "{{ calendar_mcp_gid }}"`、`system: true`。`user | Create system user` は `name: calendar-mcp`、`uid: "{{ calendar_mcp_uid }}"`、`group: calendar-mcp`、`system: true`、`shell: /usr/sbin/nologin`、`home: "{{ calendar_mcp_data_dir }}"`、`create_home: false`。

- [ ] **Step 5: `tasks/main.yml` の先頭に import を足す**

```yaml
- name: Import user tasks
  ansible.builtin.import_tasks: user.yml
  tags:
    - calendar_mcp_user
```

- [ ] **Step 6: テストを通す**

Run: `uv run --with pytest --with ansible-core pytest tests -q`
Expected: 329 passed（いまの 328 件に 1 件足した数）

- [ ] **Step 7: リントを通す**

Run: `git add roles/calendar_mcp/tasks/user.yml && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて Passed か Skipped

- [ ] **Step 8: コミット**

```bash
git -P status -sb
git add roles/calendar_mcp/tasks/user.yml roles/calendar_mcp/tasks/main.yml roles/calendar_mcp/vars/main.yml tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): register a calendar-mcp host account"
git -P log -1 --oneline
```

---

### Task 2: コンテナをそのアカウントで動かし、ファイルを持たせる

**Files:**
- Modify: `roles/calendar_mcp/templates/compose.yaml.j2`（各サービスに `user:`）
- Modify: `roles/calendar_mcp/tasks/config.yml`（`config | Deploy settings` の `group`）
- Modify: `roles/calendar_mcp/tasks/container.yml`（`container | Create data directories` の `group`、`container | Own data files` を追加）
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: Task 1 の `calendar_mcp_uid`、`calendar_mcp_gid`、`user | Create system group`、`user | Create system user`、`ACCOUNT_IDS`、`resolved`
- Produces: タスク名 `container | Own data files`（`ansible.builtin.file`）

- [ ] **Step 1: 失敗するテストを書く**

`CalendarMcpUserTest` に足す。

```python
    def test_containers_run_as_the_registered_account(self):
        services = yaml.safe_load(
            render("compose.yaml.j2", __calendar_mcp_image="calendar-mcp:x", **ACCOUNT_IDS)
        )["services"]
        for name, service in services.items():
            with self.subTest(service=name):
                self.assertEqual(service.get("user"), "1980:1981")

    def test_account_owns_the_settings_and_data(self):
        for file, name, module in (
            ("config.yml", "config | Deploy settings", "ansible.builtin.template"),
            ("container.yml", "container | Create data directories", "ansible.builtin.file"),
            ("container.yml", "container | Own data files", "ansible.builtin.file"),
        ):
            with self.subTest(task=name):
                args = task_named(file, name)[module]
                self.assertEqual(resolved(args["owner"]), "1980")
                self.assertEqual(resolved(args["group"]), "1981")

    def test_data_files_change_owner_before_the_containers_start(self):
        names = [
            task["name"]
            for task in yaml.safe_load((ROLE / "tasks" / "container.yml").read_text())
        ]
        self.assertLess(
            names.index("container | Own data files"),
            names.index("container | Start containers"),
        )
        own = task_named("container.yml", "container | Own data files")
        directories = task_named("container.yml", "container | Create data directories")
        self.assertTrue(own["ansible.builtin.file"]["recurse"])
        self.assertNotIn("mode", own["ansible.builtin.file"])
        self.assertEqual(
            own["ansible.builtin.file"]["path"], directories["ansible.builtin.file"]["path"]
        )
        self.assertEqual(own["loop"], directories["loop"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -q -k "registered_account or owns_the or change_owner"`
Expected: compose の各サービスが `None != '1980:1981'`、`config | Deploy settings` と `container | Create data directories` が `'1980' != '1981'`（group が uid の変数を読んでいる）、`container | Own data files` と `test_data_files_change_owner_before_the_containers_start` が `StopIteration` か `ValueError`（タスクがない）で失敗する

- [ ] **Step 3: compose に実行ユーザーを足す**

`compose.yaml.j2` の各サービスの `pull_policy` の後に `user: "{{ calendar_mcp_uid }}:{{ calendar_mcp_gid }}"` を置き、英語のコメントで、イメージの mcpuser の番号はホストに登録されていないので、登録したアカウントで上書きすると書く。

- [ ] **Step 4: 所有グループを gid の変数にする**

`config | Deploy settings` と `container | Create data directories` の `group` を `"{{ calendar_mcp_gid }}"` にする。

- [ ] **Step 5: `container | Own data files` を足す**

`container | Create data directories` の直後に置く。`ansible.builtin.file` で `path`、`loop`、`loop_control` は `container | Create data directories` と同じ、`state: directory`、`recurse: true`、`owner: "{{ calendar_mcp_uid }}"`、`group: "{{ calendar_mcp_gid }}"`。`mode` は書かない。英語のコメントで次の二点を書く: コンテナが別の番号で書いたファイルが残ると、0600 の鍵を読めずログにも追記できないこと。`container | Start containers` が compose の変更でその場でコンテナを作り直すので、それより前に付け替えること。`mode` を当てない理由（ファイルにディレクトリの 0750 が付く）も一行で書く。

- [ ] **Step 6: テストを通す**

Run: `uv run --with pytest --with ansible-core pytest tests -q`
Expected: 332 passed（Task 1 の 329 件に 3 件足した数）

- [ ] **Step 7: リントを通す**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて Passed か Skipped

- [ ] **Step 8: コミット**

```bash
git -P status -sb
git add roles/calendar_mcp/templates/compose.yaml.j2 roles/calendar_mcp/tasks/config.yml roles/calendar_mcp/tasks/container.yml tests/test_calendar_mcp.py
git commit -m "fix(calendar_mcp): run the containers as the calendar-mcp account"
git -P log -1 --oneline
```

コミット本文には、イメージの mcpuser（999）が fox では dnsmasq（uid）と systemd-journal（gid）の番号で、パスワードを持つ設定ファイルとデータがホストからは dnsmasq の所有に見えていたことを書く。

---

### Task 3: fox に適用して確かめる

**Files:** なし（適用と確認だけ）

**Interfaces:**
- Consumes: Task 1 と Task 2 のコミット

fork の `rewse` の先頭が 4faef82 に進んでいるので、この適用でイメージが作り直される（数分かかる）。

- [ ] **Step 1: origin と揃っていることを確かめる**

Run: `git -P fetch && git -P log --oneline HEAD..origin/main`
Expected: 何も出ない。出たら `git pull --ff-only` してから続ける

- [ ] **Step 2: 適用前の状態を記録する**

Run: `ssh fox.rewse.jp 'getent passwd 980; getent group 980; getent passwd calendar-mcp; sudo find /srv/calendar_mcp -path "*/keys/*" -type f | wc -l'`
Expected: getent は三つとも何も出さず、鍵ファイルは 2

- [ ] **Step 3: check で差分を見る**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags calendar_mcp --check --diff`
Expected: `failed=0`。変更はグループとユーザーの作成、`appsettings.json` とデータディレクトリの所有者、compose の `user:` 行、イメージのタグに限られる

- [ ] **Step 4: 適用する**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags calendar_mcp`（タイムアウトは 30 分）
Expected: 終了コード 0、`failed=0`

- [ ] **Step 5: 実行ユーザーと所有者を確かめる**

Run: `ssh fox.rewse.jp 'docker exec calendar-mcp-ts id; docker exec calendar-mcp-ubiqu id; ps -o uid=,user:20=,comm= -C dotnet; docker ps --format "{{.Names}} {{.Status}}" | grep calendar; sudo find /srv/calendar_mcp -mindepth 1 ! -user calendar-mcp; sudo stat -c "%U:%G %a %n" /etc/compose/calendar_mcp/ts/appsettings.json /etc/compose/calendar_mcp/ubiqu/appsettings.json'`
Expected: `id` は二つとも `uid=980 gid=980 groups=980`、`ps` は `980 calendar-mcp dotnet` が二行（`user` の幅を広げないと `calendar+` に切り詰められる）、両コンテナが `(healthy)`、`find` は何も出さない、`stat` は二つとも `calendar-mcp:calendar-mcp 400`

- [ ] **Step 6: 鍵とログが引き継がれたことを確かめる**

Run: `for p in /health/ts /health/ubiqu; do curl -s -o /dev/null -w "%{http_code}\n" --resolve calendar-mcp.rewse.jp:443:192.168.0.30 "https://calendar-mcp.rewse.jp$p"; done; ssh fox.rewse.jp 'sudo find /srv/calendar_mcp -path "*/keys/*" -type f | wc -l; sudo find /srv/calendar_mcp -path "*/logs/*" -mmin -5 -printf "%u %p\n"; docker logs --since 10m calendar-mcp-ts 2>&1 | grep -ciE "denied|unauthorizedaccess|exception"'`
Expected: `200` が二つ、鍵ファイルは 2 のまま、直近 5 分に更新されたログが二つ（ts と ubiqu、Apache 経由の `/health` は当日のログに残る）`calendar-mcp` の所有で出る、例外の件数は 0

- [ ] **Step 7: 2 回目の適用で変更がないことを確かめる**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags calendar_mcp`
Expected: `changed=0`、`failed=0`

- [ ] **Step 8: 古いイメージを消す**

Run: `ssh fox.rewse.jp 'docker rmi calendar-mcp:d1b40486cdf8-e646ff95d622; docker images --format "{{.Repository}}:{{.Tag}}" | grep calendar'`
Expected: 残るのは稼働中のタグ一つ

- [ ] **Step 9: push する**

```bash
git -P status -sb
git push origin main
```

Expected: spec、plan、Task 1、Task 2 のコミットが origin/main に載る。CI（Gitleaks、Lint）が成功する
