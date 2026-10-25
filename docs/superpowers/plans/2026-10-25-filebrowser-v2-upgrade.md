# filebrowser v2 アップグレード Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox の filebrowser を 1.5.8-stable から 2.0.1-stable に上げ、BoltDB の内容（admin、パスキー、共有）を SQLite に移して今と同じ使い方を保つ。

**Architecture:** 一時的な `database` コンポーネントが v1 のコンテナを止め、旧 DB を複製して `database.db.old` に改名する。`config.yaml.j2` は v2 の形にし、旧 DB がある間だけ `migrateFrom` を入れる。container は旧 DB が残っていれば起動を拒み、起動後は healthy になるまで待つ。確認後に旧 DB と一時タスクを消す。

**Tech Stack:** Ansible（community.docker.docker_compose_v2）、Apache mod_headers、FileBrowser Quantum 2.0.1、pytest（unittest、jinja2、PyYAML）

**Spec:** `docs/superpowers/specs/2026-10-25-filebrowser-v2-upgrade-design.md`

## Global Constraints

- 対象ホストは fox だけ。プレイブックは `home-primary.yml`、ロールのタグは `filebrowser`。
- イメージの選び方（`pattern='^\d+\.\d+\.\d+-stable$'`、4 日の cooldown）は変えない。今回入るのは 2.0.1-stable。
- データディレクトリは `filebrowser_data_dir`（`/srv/filebrowser`）、コンテナ内は `/home/filebrowser/data`。
- 新しい DB: `server.database.path: /home/filebrowser/data/filebrowser.sqlite`
- 移行元: `server.database.migrateFrom: /home/filebrowser/data/database.db.old`。データディレクトリに `database.db` か `database.db.old` がある間だけ入れる。
- バックアップ: `/var/backups/filebrowser/`（root 所有、`"0700"`）に `database.db` を複製し、所有者 `filebrowser_uid`:`filebrowser_gid`、`"0600"`。
- `http`: `port`、`baseURL: "/"`、`externalUrl`、`disableWebDAV: true`、`trustProxyHeaders: true`。`trustedHeaders` は書かない。
- `userDefaults.account.permissions`: `admin: false`、`api: false`、`share: true` の 3 つだけ。
- `server.database.activity` は書かない。analytics は Ansible で扱わない。
- コメントは英語で、今のコードについて書く。変更の経緯はコミットメッセージに書く。
- check mode は非破壊で失敗しない。2 回目の実行は changed=0。`command` には理由のコメントと `changed_when` を付ける。
- コミットメッセージは Conventional Commits。push の前に `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests` を通す。
- 120 秒を超える ansible-playbook は `nohup sh -c '... > LOG 2>&1; echo EXIT=$? >> LOG' &` で走らせ、`EXIT=` の行で終了コードを確かめる。

## Review Focus

- `database.db` と `database.db.old` が両方あるとき（中断した実行や切り戻しの残り）、改名は上書きせずに止まり、container は v1 の DB のまま 2.x を起動しない。Task 3 のテストで、改名の `creates` と `removes`、container の確認を固定する。
- 移行前の fox で container のタグだけを回すと、v1 の DB に 2.x が組み合わさる。check mode でない実行で失敗することを Task 3 のテストで固定する。
- 移行前の fox での check mode は失敗してはならない。container の確認が `not ansible_check_mode` を条件に持つことを Task 3 のテストで固定する。
- 初回起動の移行中に `Restart filebrowser` ハンドラが再起動すると、取り込みが途中の SQLite が残る。起動のタスクが `wait: true` を持つことを Task 3 のテストで固定する。
- クライアントが送った `X-Forwarded-Host` の先頭の値が、cookie の domain、WebAuthn の origin、共有 URL に使われる。vhost が fixups で消すことを Task 1 のテストで固定する。

---

### Task 1: vhost でクライアントの X-Forwarded-Host を消す

**Files:**
- Modify: `tests/test_internet_exposure.py`（`FileBrowserForwardedForTest`）
- Modify: `roles/filebrowser/templates/nas.rewse.jp.conf.j2`

**Interfaces:**
- Produces: vhost が `RequestHeader unset X-Forwarded-Host` を fixups で行う。

- [ ] **Step 1: 失敗するテストを書く**

```python
    def test_vhost_drops_client_forwarded_host(self):
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-Host$")
        self.assertNotRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-Host early")
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_internet_exposure.py -k forwarded_host -v`
Expected: FAIL（`RequestHeader unset X-Forwarded-Host` が無い）

- [ ] **Step 3: `RequestHeader unset X-Forwarded-For` の直後に `RequestHeader unset X-Forwarded-Host` を足す**

コメントには、FileBrowser が `X-Forwarded-Host` の先頭の値を cookie の domain、WebAuthn の origin、共有 URL に使うこと、mod_proxy はクライアントの値に追記するので fixups で消せば mod_proxy が付ける本来のホストだけが残ることを書く。fixups で行う理由は既存の `X-Forwarded-For` のコメントと共有する。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_internet_exposure.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_internet_exposure.py roles/filebrowser/templates/nas.rewse.jp.conf.j2
git commit -m "fix(filebrowser): drop client X-Forwarded-Host at the proxy"
```

### Task 2: config.yaml を v2 の形にする

**Files:**
- Create: `tests/test_filebrowser.py`
- Modify: `roles/filebrowser/templates/config.yaml.j2`
- Modify: `roles/filebrowser/tasks/config.yml`

**Interfaces:**
- Produces: `config.yml` の `config | Find v1 database`（`ansible.builtin.find`、`paths: "{{ filebrowser_data_dir }}"`、`patterns: [database.db, database.db.old]`）が `__filebrowser_boltdb_files` を登録する。テンプレートは `__filebrowser_boltdb_files.matched > 0` のときだけ `migrateFrom` を出す。
- Produces: `tests/test_filebrowser.py` の `ROLE = REPO_ROOT / "roles" / "filebrowser"`、`render_config(matched: int) -> dict`、`tasks(name: str) -> dict[str, dict]`（`ROLE / "tasks" / name` のタスクを名前で引く。順序は保つ）。

- [ ] **Step 1: 失敗するテストを書く**

`render_config` は `ROLE / "templates"` を jinja2（`StrictUndefined`、`comment` フィルタは `tests/test_fail2ban_apache.py` の `render` と同じ）で描画して `yaml.safe_load` する。変数は `filebrowser_port=8080`、`filebrowser_hostname="nas.rewse.jp"`、`filebrowser_sources=[{"name": "Home", "path": "/srv/nas/data/homes/tats", "rules": []}]`、`admin_user="tats"`、`filebrowser_admin_password="pw"`、`filebrowser_jwt_secret="key"`、`filebrowser_token_expiration_hours=720`、`__filebrowser_boltdb_files={"matched": matched}`。

```python
class FileBrowserConfigTest(unittest.TestCase):
    def test_http_settings_live_under_http(self):
        config = render_config(0)
        self.assertEqual(config["http"], {
            "port": 8080,
            "baseURL": "/",
            "externalUrl": "https://nas.rewse.jp",
            "disableWebDAV": True,
            "trustProxyHeaders": True,
        })
        for key in ("port", "baseURL", "externalUrl", "disableWebDAV"):
            self.assertNotIn(key, config["server"])

    def test_database_has_no_migration_source_without_v1_database(self):
        self.assertEqual(render_config(0)["server"]["database"],
                         {"path": "/home/filebrowser/data/filebrowser.sqlite"})

    def test_database_migrates_while_v1_database_remains(self):
        self.assertEqual(render_config(1)["server"]["database"], {
            "path": "/home/filebrowser/data/filebrowser.sqlite",
            "migrateFrom": "/home/filebrowser/data/database.db.old",
        })

    def test_user_defaults_keep_only_account_permissions(self):
        self.assertEqual(render_config(0)["userDefaults"],
                         {"account": {"permissions": {"admin": False, "api": False, "share": True}}})

    def test_source_and_auth_are_unchanged(self):
        config = render_config(0)
        (source,) = config["server"]["sources"]
        self.assertEqual(source["config"]["readOnly"], True)
        self.assertEqual(source["config"]["defaultEnabled"], True)
        self.assertEqual(source["config"]["rules"], [{"ignoreHidden": True}])
        self.assertEqual(config["server"]["cacheDir"], "/home/filebrowser/data/cache")
        self.assertEqual(config["auth"]["methods"]["passkey"]["rpId"], "nas.rewse.jp")
        self.assertEqual(config["auth"]["methods"]["passkey"]["rpOrigins"], ["https://nas.rewse.jp"])

    def test_config_task_finds_v1_database_before_rendering(self):
        config = tasks("config.yml")
        names = list(config)
        find = config["config | Find v1 database"]["ansible.builtin.find"]
        self.assertEqual(find["patterns"], ["database.db", "database.db.old"])
        self.assertEqual(config["config | Find v1 database"]["register"], "__filebrowser_boltdb_files")
        self.assertLess(names.index("config | Find v1 database"),
                        names.index("config | Deploy configuration file"))
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_filebrowser.py -v`
Expected: FAIL（`http` に `port` などが無い、`database` が文字列、`config | Find v1 database` が無い）

- [ ] **Step 3: `config.yml` の「Create data directory」と「Deploy configuration file」の間に `config | Find v1 database` を足す**

- [ ] **Step 4: `config.yaml.j2` を v2 の形に書き換える**

Global Constraints の値どおりに `http` と `server.database` を作る。`userDefaults` から `create`、`delete`、`modify` と、share のコメントにある 1.x の版番号の話を消す。`trustedHeaders` のコメントは、`trustProxyHeaders` が Apache の後ろでロックアウトと回数制限、操作ログの IP、WebAuthn の origin、cookie を正しくすることと、vhost がクライアントの `X-Forwarded-For` と `X-Forwarded-Host` を消しているので信頼してよいことに書き直す。`migrateFrom` のコメントには、旧 DB が残っている間だけ入ることと、SQLite が空でなければ無視されることを書く。書き終えたら、v2.0.1 の `backend/pkg/settings/structs.go` と `backend/pkg/settings/auth.go`（`https://raw.githubusercontent.com/gtsteffaniak/filebrowser/v2.0.1-stable/...`）の `json` タグと、テンプレートのキーの置き場所を突き合わせる。

- [ ] **Step 5: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_filebrowser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_filebrowser.py roles/filebrowser/templates/config.yaml.j2 roles/filebrowser/tasks/config.yml
git commit -m "feat(filebrowser): write the configuration in the v2 format"
```

### Task 3: 旧 DB の退避と、起動の守り

**Files:**
- Create: `roles/filebrowser/tasks/database.yml`
- Modify: `roles/filebrowser/tasks/main.yml`
- Modify: `roles/filebrowser/tasks/container.yml`
- Modify: `tests/test_filebrowser.py`

**Interfaces:**
- Consumes: Task 2 の `tasks(name)`
- Produces: `database.yml` のタスク（この順）`database | Check v1 database`（`__filebrowser_boltdb`）、`database | Check compose file`（`__filebrowser_compose_file`、`/etc/compose/filebrowser/compose.yaml`）、`database | Create backup directory`、`database | Stop container`、`database | Back up v1 database`、`database | Rename v1 database for migration`、`database | Report migration in check mode`。
- Produces: `container.yml` の `container | Check v1 database`（`__filebrowser_boltdb_left`）、`container | Fail when v1 database is not migrated`、`container | Report unmigrated database in check mode`。

- [ ] **Step 1: 失敗するテストを書く**

```python
class FileBrowserMigrationTest(unittest.TestCase):
    def test_database_component_runs_before_config(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        files = [task["ansible.builtin.import_tasks"] for task in imports]
        self.assertLess(files.index("database.yml"), files.index("config.yml"))
        (database,) = [t for t in imports if t["ansible.builtin.import_tasks"] == "database.yml"]
        self.assertEqual(database["tags"], ["filebrowser_database"])

    def test_v1_database_is_stopped_backed_up_and_renamed_only_when_present(self):
        database = tasks("database.yml")
        stop = database["database | Stop container"]
        self.assertEqual(stop["community.docker.docker_compose_v2"]["state"], "stopped")
        self.assertIn("__filebrowser_compose_file.stat.exists", stop["when"])
        backup = database["database | Back up v1 database"]["ansible.builtin.copy"]
        self.assertTrue(backup["remote_src"])
        self.assertEqual(backup["dest"], "/var/backups/filebrowser/database.db")
        self.assertEqual(backup["mode"], "0600")
        rename = database["database | Rename v1 database for migration"]
        self.assertEqual(rename["args"]["removes"], "{{ filebrowser_data_dir }}/database.db")
        self.assertEqual(rename["args"]["creates"], "{{ filebrowser_data_dir }}/database.db.old")
        self.assertIn("changed_when", rename)
        for name in ("database | Stop container", "database | Back up v1 database"):
            self.assertIn("__filebrowser_boltdb.stat.exists", database[name]["when"])

    def test_container_refuses_an_unmigrated_database_outside_check_mode(self):
        container = tasks("container.yml")
        names = list(container)
        guard = container["container | Fail when v1 database is not migrated"]
        self.assertIn("__filebrowser_boltdb_left.stat.exists", guard["when"])
        self.assertIn("not ansible_check_mode", guard["when"])
        self.assertLess(names.index("container | Fail when v1 database is not migrated"),
                        names.index("container | Start container"))

    def test_start_waits_until_healthy(self):
        start = tasks("container.yml")["container | Start container"]["community.docker.docker_compose_v2"]
        self.assertTrue(start["wait"])
        self.assertEqual(start["wait_timeout"], 300)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_filebrowser.py -k Migration -v`
Expected: FAIL（`database.yml` が無い）

- [ ] **Step 3: `tasks/database.yml` を書く**

ファイル先頭のコメントに、v1 から v2 への一度きりの移行で、fox が収束したら消すことを書く。`Create backup directory` 以降は `__filebrowser_boltdb.stat.exists` を条件にし、`Stop container` にはさらに `__filebrowser_compose_file.stat.exists` を付ける（初めて入れるホストにはまだ compose が無い）。止める理由（動いている v1 が BoltDB をロックしている）をコメントに書く。ディレクトリは root 所有で `"0700"`、複製は Global Constraints の所有者とモード。改名は `ansible.builtin.command: mv {{ filebrowser_data_dir }}/database.db {{ filebrowser_data_dir }}/database.db.old` で、ファイルを改名するモジュールが無いことをコメントに書き、`args` に `creates` と `removes`、`changed_when: true` を付ける（`creates` と `removes` があると check mode では実行せずに changed を予測し、両方のファイルがあれば上書きせずに飛ばす）。`Report migration in check mode` は `verbosity: 0` で、`ansible_check_mode and __filebrowser_boltdb.stat.exists` のときに移行が走ることを伝える。

- [ ] **Step 4: `tasks/main.yml` の先頭に database の import を足す**

```yaml
- name: Import database tasks
  ansible.builtin.import_tasks: database.yml
  tags:
    - filebrowser_database
```

- [ ] **Step 5: `container.yml` を直す**

「Deploy compose file」の後、「Report skipped start in check mode」の前に `container | Check v1 database`（stat `{{ filebrowser_data_dir }}/database.db`）、`container | Fail when v1 database is not migrated`（`when: [__filebrowser_boltdb_left.stat.exists, not ansible_check_mode]`、メッセージで `filebrowser_database` タグを含めて回すよう案内する）、`container | Report unmigrated database in check mode`（`verbosity: 0`）を足す。「Start container」に `wait: true` と `wait_timeout: 300` を足し、v2 は移行を HTTP サーバーの前に行うので healthy まで待てば後のハンドラの再起動が移行を中断しない、とコメントに書く。「Resolve aged image」のコメントから v2 が preview だという記述を消し、beta と preview のタグが同じリポジトリにあるので stable の行だけを追う理由は残す。

- [ ] **Step 6: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add roles/filebrowser/tasks/database.yml roles/filebrowser/tasks/main.yml roles/filebrowser/tasks/container.yml tests/test_filebrowser.py
git commit -m "feat(filebrowser): migrate the v1 database when upgrading to v2"
```

### Task 4: 事前確認と push

**Files:** なし

- [ ] **Step 1: lint とテスト**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも exit 0。フックが直したファイルがあればコミットする。

- [ ] **Step 2: リポジトリを最新にする**

Run: `git -P fetch && git -P log --oneline HEAD..origin/main`
Expected: 出力なし。あれば fast-forward してから続ける。

- [ ] **Step 3: check mode**

Run: `direnv exec . ansible-playbook home-primary.yml --tags filebrowser --check --diff`（nohup）
Expected: `EXIT=0`、failed=0。`database | Report migration in check mode` と `container | Report unmigrated database in check mode` が出る。compose の差分は image が `ghcr.io/gtsteffaniak/filebrowser:2.0.1-stable@sha256:…` に変わるだけ、vhost の差分は `RequestHeader unset X-Forwarded-Host` とそのコメントの追加だけ。

- [ ] **Step 4: バックアップ先と古い形の共有リンク**

Run: `ssh -p 11022 fox.rewse.jp "grep -n -E 'var/backups|^backups' /etc/restic.exclude; sudo zgrep -h '^nas.rewse.jp:443 ' /var/log/apache2/other_vhosts_access.log* | grep -c '\"GET /share/'"`
Expected: `restic.exclude` に `/var/backups` を外す行が無く、`/share/` の件数が 0。除外されていたら利用者に知らせ、バックアップ先を決め直す。件数が 1 以上なら件数と最終日時を利用者に知らせる（リダイレクトは足さない）。

- [ ] **Step 5: push**

Run: `git -P push`
Expected: main に push される。

### Task 5: 移行の実行と確認

**Files:** fail2ban のステータスが違ったときだけ `roles/filebrowser/templates/fail2ban-filter.conf.j2` と `tests/test_filebrowser.py`

- [ ] **Step 1: 適用**

Run: `direnv exec . ansible-playbook home-primary.yml --tags filebrowser`（nohup）
Expected: `EXIT=0`、failed=0。`database | Rename v1 database for migration` が changed、`container | Start container` が healthy を待って終わる。

- [ ] **Step 2: 移行のログと状態**

Run: `ssh -p 11022 fox.rewse.jp 'sudo docker logs filebrowser 2>&1 | grep -iE "migrat"; sudo docker ps --filter name=filebrowser --format "{{.Image}} {{.Status}}"; sudo ls -la /srv/filebrowser /var/backups/filebrowser'`
Expected: `Migration completed successfully!` と users、shares などの件数が出る。コンテナは `2.0.1-stable` で `(healthy)`。データディレクトリに `filebrowser.sqlite` と `database.db.old` があり、`database.db` は無い。バックアップに `database.db`（`0600`、uid 2000）がある。

- [ ] **Step 3: 2 回目の実行**

Run: `direnv exec . ansible-playbook home-primary.yml --tags filebrowser`
Expected: changed=0

- [ ] **Step 4: ログイン失敗のステータスと fail2ban**

alfa から CloudFront 経由で間違ったパスワードを 1 回だけ送る。CloudFront の IP は `dig +short nas.rewse.jp @8.8.8.8 | tail -1`、alfa のグローバル IP は `curl -s https://checkip.amazonaws.com` で得る。

Run: `curl -s -o /dev/null -w '%{http_code}\n' --resolve nas.rewse.jp:443:<CloudFront IP> -X POST https://nas.rewse.jp/api/auth/login -H 'Content-Type: application/json' -d '{"username":"tats","password":"wrong"}'`。続けて fox で `sudo fail2ban-regex /var/log/apache2/other_vhosts_access.log /etc/fail2ban/filter.d/filebrowser.conf | grep -E 'Failregex|matched'`
Expected: 401 か 403 が返り、`fail2ban-regex` が 1 件以上一致する（1 回では maxretry の 5 に届かず BAN されない）。パスキー登録済みの admin に正しいパスワードだけで入る場合（v1 では 403）は、本物のパスワードをコマンドラインに載せることになるので試さない。フィルタは 403 も数えているので、間違ったパスワードの結果だけで判断する。別のステータス（429 を含む）なら、`tests/test_filebrowser.py` に、`fail2ban-filter.conf.j2` を `regex_escape` を `re.escape` にして描画し、`<HOST>` を `(?P<host>\S+)` に置き換えた正規表現が、そのステータスの実際のログ行に一致するテストを足す。フィルタの `(?:401|403)` にそのステータスを足し、テストが通ったらコミットして `filebrowser_fail2ban` タグで適用し、`fail2ban-regex` で一致を確かめる。

- [ ] **Step 5: 転送ヘッダーの効き目**

管理画面の操作ログで、Step 4 の失敗が alfa のグローバル IP で記録されていることを確かめる。共有リンクを 1 つ開き、URL が `https://nas.rewse.jp/public/share/…` であることを確かめる。
Expected: どちらも満たす。

- [ ] **Step 6: 利用者による確認**

利用者にスマホで、パスワードとパスキー（Face ID）でログインできること、Home を閲覧と検索できること、アップロード、削除、名前の変更が出ないこと、既存の共有リンクが開いてパスワードを聞かれることを確かめてもらう。続けて、管理画面で analytics のプレビューを見てからオンにしてもらう。
Expected: 全部できる。1 つでも駄目なら「切り戻し」に進む。

### Task 6: 後片付け

**Files:**
- Delete: `roles/filebrowser/tasks/database.yml`
- Modify: `roles/filebrowser/tasks/main.yml`、`roles/filebrowser/tasks/config.yml`、`roles/filebrowser/tasks/container.yml`、`roles/filebrowser/templates/config.yaml.j2`、`tests/test_filebrowser.py`

- [ ] **Step 1: 旧 DB をデータディレクトリから消す**

Run: `ssh -p 11022 fox.rewse.jp 'sudo cmp /srv/filebrowser/database.db.old /var/backups/filebrowser/database.db && sudo rm /srv/filebrowser/database.db.old'`
Expected: `cmp` が一致して exit 0。一致しなければ消さずに理由を調べる。

- [ ] **Step 2: テストを後片付け後の形にする**

`FileBrowserMigrationTest` は `test_start_waits_until_healthy` だけを残す。`FileBrowserConfigTest` の `test_database_migrates_while_v1_database_remains` と `test_config_task_finds_v1_database_before_rendering` を消し、`render_config` から引数と `__filebrowser_boltdb_files` を外して、残るテストの呼び出しを `render_config()` にそろえる。次の 2 つを足す。

```python
    def test_v1_migration_is_gone(self):
        imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        self.assertNotIn("database.yml", [t["ansible.builtin.import_tasks"] for t in imports])
        self.assertNotIn("container | Fail when v1 database is not migrated", tasks("container.yml"))

    def test_template_has_no_migration_source(self):
        self.assertNotIn("migrateFrom", (ROLE / "templates" / "config.yaml.j2").read_text())
```

- [ ] **Step 3: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_filebrowser.py -v`
Expected: FAIL（まだ import と `migrateFrom` が残っている）

- [ ] **Step 4: 一時コードを消す**

`database.yml` を消し、`main.yml` の import、`config.yml` の `config | Find v1 database`、テンプレートの `migrateFrom` とその条件とコメント、`container.yml` の 3 つの確認タスクを消す。`wait: true` とそのコメントは残す。

- [ ] **Step 5: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -v`
Expected: PASS

- [ ] **Step 6: 適用と 2 回目の実行**

Run: `direnv exec . ansible-playbook home-primary.yml --tags filebrowser --check --diff`、続けて check を外して適用し、もう一度適用する（どれも nohup）。
Expected: check は `EXIT=0`。適用で config が変わって再起動し、healthy になる。もう一度の適用は changed=0。利用者にログインと閲覧ができることを確かめてもらう。

- [ ] **Step 7: lint、テスト、Commit、push**

Task 4 の Step 1 と Step 2 を行ってから:

```bash
git add -A roles/filebrowser tests/test_filebrowser.py
git commit -m "refactor(filebrowser): remove the completed v1 database migration"
git -P push
```

## 切り戻し

Task 5 か Task 6 で問題が出たら行う。

1. `ssh -p 11022 fox.rewse.jp 'sudo docker compose -f /etc/compose/filebrowser/compose.yaml stop'`
2. fox で `filebrowser.sqlite` を `/var/backups/filebrowser/` に退避し、`/var/backups/filebrowser/database.db` を `/srv/filebrowser/database.db` に戻す（所有者 2000:2000、`0600`）。`database.db.old` は消す。
3. このプランのコミットを `git revert` し、`container.yml` の `pattern` を `'^1\.\d+\.\d+-stable$'` に変え、v2 への移行が済むまで 1.x に止める理由をコメントに書いてコミットする。
4. `direnv exec . ansible-playbook home-primary.yml --tags filebrowser` で 1.5.8 に戻し、ログインと共有リンクを確かめる。
5. 不具合を upstream の issue にするかを利用者と決める。

## 後続

- 2026-10-28 以降の update で 2.0.2-stable が入って動いたら、`/var/backups/filebrowser/` を消す。
