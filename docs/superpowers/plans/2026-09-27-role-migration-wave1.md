# 既存ロールの移行 波 1（フラットな小さいロール）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** フラットな名前の小さいロール 20 個を AGENTS.md の規約に合わせ、その `.ansible-lint-ignore` の行を消す。あわせて `aged_release` と、波 1 のロールに属する持ち越しの不具合を直す。

**Architecture:** ロールごとに `tasks/main.yml` を `import_tasks` だけにし、コンポーネントのファイルに分ける。改名と分割はホストの状態を変えないため、`--check --diff` の差分は下の「意図した変更」だけになる。`aged_release` は pytest で先に失敗するテストを書いてから直す。

**Tech Stack:** ansible-core、ansible-lint（pre-commit 経由）、pytest（`uv run --with pytest --with ansible-core`）

**Spec:** `docs/superpowers/specs/2026-09-27-role-migration-design.md`

## Global Constraints

- ブランチは `refactor/role-migration-wave1`。ロールごとに Conventional Commits でコミットする（例: `refactor(syslogd): split into components`）
- 各ロールで AGENTS.md の「ロールごとの作業」のチェックリストを満たし、そのロールの `.ansible-lint-ignore` の行を消す。`ansible-lint roles/<role>` が ignore なしで 0 件になること
- コンポーネント名、ファイル名、タグは各タスクの表のとおりにする。タグはロール名、`<role>_<component>`、`update`、`always` だけにする
- handler 名は `<動詞> <サービス>` にする。複数のロールが同じ名前の handler を定義するときは、本体を次の形にそろえる（同名の handler は最後に読んだものだけが動くため）
  - `Reload Apache`: `ansible.builtin.systemd: {name: apache2, state: reloaded}`
  - `Restart Apache`: `ansible.builtin.systemd: {name: apache2, state: restarted}`
  - `Restart zabbix-agent`: `ansible.builtin.systemd: {name: zabbix-agent, state: restarted}`
  - `Reload systemd`: `ansible.builtin.systemd: {daemon_reload: true}`
- 波 2 以降のロールが使う旧名の handler（`apache: Reload` など）は、そのロールの移行まで残す
- matter_server のデータは `/srv/matter-server` から AGENTS.md どおりの `/srv/matter_server` に移す
- 意図した変更（check の差分に出てよいもの）は次だけである: couchdb の init スクリプトの置き場所、mosquitto のパスワードのスタンプ、power_monitor の `config.dist`、matter_server のデータの `/srv/matter_server` への移動と compose のマウント、古い `/etc/matter-server` の削除
- ホストへの反映は Task 9 でまとめて行い、`--check --diff` の差分を見せて承認を得てからにする

## Review Focus

- タグで 1 コンポーネントだけ流したとき（`--tags <role>_<component>`）に、前提のディレクトリや変数がそろっていて失敗しない。各タスクで `--list-tasks --tags` と `--check --tags` を流して確かめる
- 同名の handler の本体がロール間で食い違うと、片方の再起動が黙って別の動作になる。Task 9 で `rg -A3 '^- name: (Reload|Restart) '` で本体を比べる
- `aged_release` のページングで、ページの配列を平らにし忘れると、最新のタグが見つからずエラーになる。Task 1 に 2 ページのテストを置く
- teslamate の順序の契約（イメージの取得が compose の変更より先）が、ファイル分割で壊れる。Task 5 でテストを新しいファイルに向けて通す
- mosquitto のパスワードを変えたのに、スタンプだけが変わって pwfile が更新されない。Task 7 でスタンプの変更が 3 つの handler を順に呼ぶことを `--check --diff` で確かめる

---

### Task 1: `aged_release` の強化

**Files:**
- Modify: `plugins/lookup/aged_release.py`
- Test: `tests/test_aged_release.py`

**Interfaces:**
- Produces: 戻り値の形は変えない。変わるのは `gh api` の呼び出し（`--paginate --slurp` 付き）、エラーの文言、`_parse_time` の挙動

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_release_error_names_repository():
    # The only release is one day old, so select() finds nothing.
    run = FakeRun({"gh api --paginate --slurp repos/o/r/releases?per_page=100":
                   [[{"tag_name": "v1.0", "published_at": iso(ago(1)), "draft": False,
                      "prerelease": False, "assets": []}]]})
    with pytest.raises(AnsibleLookupError, match="github-release:o/r: o/r: no version"):
        aged_release.resolve("github-release:o/r", pattern=r"^v?\d+(\.\d+)+$", days=4,
                             platform=None, asset=None, run=run, now=NOW)

def test_tags_are_read_across_pages():
    # Page 1 holds only a too-new tag; the aged one is on page 2.
    run = FakeRun({
        "gh api --paginate --slurp repos/o/r/tags?per_page=100":
            [[{"name": "v2.0", "commit": {"sha": "new"}}], [{"name": "v1.0", "commit": {"sha": "old"}}]],
        "gh api repos/o/r/commits/new": {"commit": {"committer": {"date": iso(ago(1))}}},
        "gh api repos/o/r/commits/old": {"commit": {"committer": {"date": iso(ago(5))}}},
    })
    result = aged_release.resolve("github-tag:o/r", pattern=r"^v?\d+(\.\d+)+$", days=4,
                                  platform=None, asset=None, run=run, now=NOW)
    assert result == {"version": "v1.0", "commit": "old"}

def test_parse_time_honours_offset():
    assert aged_release._parse_time("2026-09-20T09:00:00+09:00") == datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)

def test_parse_time_accepts_nanoseconds_and_z():
    assert aged_release._parse_time("2026-09-20T00:00:00.123456789Z") == datetime(2026, 9, 20, 0, 0, 0, 123456, tzinfo=timezone.utc)

def test_image_created_before_2000_is_rejected():
    # Reproducible builds set Created to the epoch, which would skip the cooldown.
    with pytest.raises(AnsibleLookupError, match="before 2000"):
        ...oci with Created "1970-01-01T00:00:00Z"...
```

既存テストの `FakeRun` のキーを、`gh api --paginate --slurp repos/o/r/tags?per_page=100` の形に合わせて直す。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run -q --with pytest --with ansible-core pytest tests/test_aged_release.py -q`
Expected: 新しい 5 件が FAIL

- [ ] **Step 3: 実装する**

- `_release` と `_tag` の一覧取得を `gh api --paginate --slurp <path>` にし、ページの配列を平らにしてから使う
- `_release`、`_tag`、`_oci` で `select()` などの `AnsibleLookupError` を受け、`f"{repo}: {exc}"` で投げ直す
- `_parse_time` は `Z` を `+00:00` にし、小数秒を 6 桁に切ってから `datetime.fromisoformat` で読み、UTC に変換する
- `_oci` は `Created` が 2000 年より前ならエラー（`"<repo>:<tag> Created ... is before 2000"`）にする

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run -q --with pytest --with ansible-core pytest tests/test_aged_release.py -q`
Expected: `20 passed`

Run: `direnv exec . ansible localhost -m debug -a "msg={{ lookup('aged_release', 'github-tag:make-all/tuya-local') }}"`
Expected: 現在のタグ（241 件を超えて読んでも最新が選ばれる）

- [ ] **Step 5: コミット**

`fix(aged_release): paginate, name the repository in errors, and parse offsets`

### Task 2: 小さいロール（autodiscover、dsm、lmstudio、syslogd、udm）

**Files:** 各ロールの `tasks/`、`handlers/main.yml`、`udm.yml`、`.ansible-lint-ignore`

| ロール | コンポーネント（ファイル） | handler |
|---|---|---|
| autodiscover | `apache`（3 タスク） | `Reload Apache`、`Restart Apache` |
| dsm | `ssh`、`sudo` | `Restart ssh` |
| lmstudio | `apache`（3 タスク） | `Reload Apache`、`Restart Apache` |
| syslogd | `rsyslog`、`logrotate` | `Restart rsyslog`、`Restart logrotate` |
| udm | `rp_filter` | `Restart udm-rp-filter` |

`udm.yml` の play に `name: Configure UniFi Dream Machine` とロールのタグ `udm` を付ける。

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/autodiscover roles/dsm roles/lmstudio roles/syslogd roles/udm udm.yml`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: タグと check を確かめる**

Run: `direnv exec . ansible-playbook home-primary.yml --list-tasks --tags autodiscover_apache,lmstudio_apache,syslogd_rsyslog` と、`home-primary.yml --check --diff --tags autodiscover,lmstudio,syslogd`、`udm.yml --check --diff`
Expected: 一覧にそれぞれのタスクが出て、check は exit 0、`changed=0`

- [ ] **Step 3: ロールごとにコミット**

### Task 3: 土台のロール（chezmoi、desktop、docker、ec2）

| ロール | コンポーネント | 補足 |
|---|---|---|
| chezmoi | `package`（Homebrew と Linux のスクリプト）、`source`（初期化の確認と init） | |
| desktop | `package`、`terminal` | `terminal` は `update` タグ（aged_release を使う）。`Remove legacy checkout` を消す |
| docker | `package`、`group`、`daemon`、`compose` | `Remove shared compose file` を消す。handler は `Reload docker`、`Restart zabbix-agent` |
| ec2 | `package`、`storage` | |

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/chezmoi roles/desktop roles/docker roles/ec2`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `cloud-workstation.yml --check --diff --tags chezmoi,desktop,docker,ec2` と、`home-primary.yml --check --diff --tags chezmoi,docker`
Expected: exit 0。docker の `group` 以外は `changed=0`

- [ ] **Step 3: ロールごとにコミット**

### Task 4: compose のサービス（couchdb、litellm、matter_server、nvr）と restart handler のガード

| ロール | コンポーネント | 補足 |
|---|---|---|
| couchdb | `container`、`database`、`deno`、`apache` | `container` と `deno` は `update` タグ |
| litellm | `config`、`container` | `container` は `update` タグ |
| matter_server | `container` | `update` タグ |
| nvr | `storage`、`config`、`container`、`zabbix`、`apache` | `container` は `update` タグ。`backup: true` を消す |

- couchdb の init スクリプトは、`aged_release` の `github-commit:vrtmrz/obsidian-livesync` で得たコミットの raw URL から `/usr/local/src/couchdb-init.sh` に取得する。`Run init script` はダウンロードが changed のときだけ流す
- matter_server のデータを `/srv/matter_server` に移す。`container` の先頭で次の順に行う
  - `/srv/matter-server` を `stat` し、あれば `docker_compose_v2` で `state: stopped` にしてから `command: mv /srv/matter-server /srv/matter_server`（`creates: /srv/matter_server`、`removes: /srv/matter-server`。モジュールがないため `command` にする）
  - `/srv/matter_server/data` を作り、compose のマウントを `/srv/matter_server/data:/data` にする。compose の変更で `Start containers` がコンテナを作り直す
  - 空の `/etc/matter-server` を消す
  - 事前のバックアップは取らない。データは 2.9M の JSON 2 つで、`mv` は同じファイルシステム内の rename なので途中で壊れない
- filebrowser、litellm、couchdb の restart handler に、nvr と同じ `when: not ansible_check_mode` を付ける

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/couchdb roles/litellm roles/matter_server roles/nvr roles/filebrowser`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `home-primary.yml --check --diff --tags couchdb,litellm,matter_server,nvr,filebrowser`
Expected: exit 0。changed は couchdb の init スクリプト（新しい場所への初回の取得）、matter_server の停止と移動（check では skip）、データディレクトリ、compose のマウントの差分、`/etc/matter-server` の削除だけ

- [ ] **Step 3: ロールごとにコミット**

### Task 5: teslamate

**Files:** `roles/teslamate/tasks/`、`roles/teslamate/tests/test_deployment_order.py`

| コンポーネント | 中身 |
|---|---|
| `config` | データディレクトリ、RDS の CA バンドル、2 つの env ファイル |
| `container` | イメージの解決、pre-pull、compose、legacy の dashboard patch の削除（収束済みなら削除タスクごと消す） |
| `apache` | 認証ユーティリティ、モジュール、パスワードファイル、サイト |

`container` は `update` タグにする。`backup: true` を 2 か所消す。handler は `Restart teslamate`、`Restart teslamate-grafana`、`Validate Apache configuration`、`Reload Apache`。

- [ ] **Step 1: テストを新しいファイルとタスク名に向ける**

`TASKS_PATH` を `tasks/container.yml` にし、タスク名を `container | Pre-pull deployment images`、`container | Deploy compose file`、`container | Pull and update containers` にする。legacy の削除タスクを消すなら、その assertion も消す。

- [ ] **Step 2: テストの失敗を確かめる**

Run: `uv run -q --with pytest --with pyyaml pytest roles/teslamate/tests -q`
Expected: FAIL（`container.yml` がまだない）

- [ ] **Step 3: 分割する**

- [ ] **Step 4: テスト、lint、check を確かめる**

Run: `uv run -q --with pytest --with pyyaml pytest roles/teslamate/tests -q`、`ansible-lint --nocolor roles/teslamate`、`home-primary.yml --check --diff --tags teslamate`
Expected: テストが PASS、lint が 0 件、check が exit 0 で `changed=0`

- [ ] **Step 5: コミット**

### Task 6: timer のサービス（enecoq_data_fetcher、mhz19、sslcert）

| ロール | コンポーネント | 補足 |
|---|---|---|
| enecoq_data_fetcher | `browser`（playwright の chromium）、`service`（データディレクトリ、スクリプト、service、timer） | `browser` は `update` タグ |
| mhz19 | `publisher`（ディレクトリ、venv、パッケージ、スクリプト）、`timer` | `publisher` は `update` タグ |
| sslcert | `certbot`（前提のパッケージ、venv、renew スクリプト）、`timer`、`apache` | `certbot` は `update` タグ |

handler は `Reload systemd` と、`Restart <name> timer` の形にする。

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/enecoq_data_fetcher roles/mhz19 roles/sslcert`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `home-primary.yml --check --diff --tags enecoq_data_fetcher,mhz19,sslcert`、`home-secondary.yml --check --diff --tags mhz19,sslcert`、`cloud-workstation.yml --check --diff --tags sslcert`
Expected: exit 0、`changed=0`

- [ ] **Step 3: ロールごとにコミット**

### Task 7: httpd と mosquitto

| ロール | コンポーネント | 補足 |
|---|---|---|
| httpd | `set_vars`（`always`）、`package`（/srv/www、/var/www のリンク、パッケージ、モジュール）、`default_site`（default-ssl と ServerName などの行）、`conf`（force SSL、blog redirect、admin、status、phpinfo）、`php`、`zabbix` | handler は `Reload Apache`、`Restart Apache`、`Restart zabbix-agent` |
| mosquitto | `package`、`auth` | 下のスタンプの方式にする |

mosquitto の `auth`:

- パスワードファイルの平文をホストに残さないまま、変更したときだけ作り直す。`/etc/mosquitto/pwfile.sha256` に `lookup('template', 'pwfile.j2') | hash('sha256')` を `copy` で書き、このタスクから 3 つの handler を順に呼ぶ
  - `Write mosquitto password file`: `pwfile.j2` を `/etc/mosquitto/pwfile` に書く（`mosquitto:mosquitto`、`"0600"`）
  - `Hash mosquitto password file`: `mosquitto_passwd -U /etc/mosquitto/pwfile`
  - `Restart mosquitto`
- handler はこの順に定義する（handler は定義の順に動く）

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/httpd roles/mosquitto`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `home-primary.yml --check --diff --tags httpd,mosquitto`、`cloud-workstation.yml --check --diff --tags httpd`
Expected: exit 0。changed は mosquitto のスタンプ（初回）と、それが呼ぶ 3 つの handler だけ

- [ ] **Step 3: ロールごとにコミット**

### Task 8: power_monitor

| コンポーネント | 中身 |
|---|---|
| `package` | Homebrew の前提パッケージ |
| `app` | Release の解決、インストール（`update` タグ） |
| `config` | ディレクトリ、MQTT スクリプト、設定、スクリプトのテスト |

設定は、配布元のファイルを `~/.config/power-monitor-mqtt/config.dist` に取得し、`slurp` で読んで、`MQTT_HOST=` と `MQTT_PASSWORD=` の行を `regex_replace` で置き換えた内容を `copy` で `config`（`"0600"`）に書く。配布元が変わったときと、値が変わったときだけ changed になる。`register` は `__power_monitor_` で始め、`Display test results` の `debug` に `verbosity: 1` を付ける。

- [ ] **Step 1: 分割して lint を通す**

Run: `ansible-lint --nocolor roles/power_monitor`（`roles/power_monitor/tests` の ignore の行も消す）
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `darwin-personal.yml --check --diff --tags power_monitor`
Expected: exit 0。changed は `config.dist`（初回）と `config` だけ。`config` の差分は内容が同じで、差分なしであること

- [ ] **Step 3: コミット**

### Task 9: 波 1 の検証とマージ

- [ ] **Step 1: 全体の lint とテスト**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`、2 つの pytest
Expected: すべて Passed。`rg '^(udm\.yml|roles/(autodiscover|chezmoi|couchdb|desktop|docker|dsm|ec2|enecoq_data_fetcher|filebrowser|httpd|litellm|lmstudio|matter_server|mhz19|mosquitto|nvr|power_monitor|sslcert|syslogd|teslamate|udm)/)' .ansible-lint-ignore` が 0 件

- [ ] **Step 2: 同名の handler の本体を比べる**

Run: `rg -N -A3 '^- name: (Reload|Restart) (Apache|zabbix-agent|systemd)$' roles/*/handlers/main.yml`
Expected: 同じ名前の本体がすべて Global Constraints のとおり

- [ ] **Step 3: 5 台で check**

Run: `home-primary.yml`、`home-secondary.yml`、`cloud-workstation.yml`、`darwin-personal.yml`、`udm.yml` を `--check --diff` で、タグなしで流す
Expected: 波 1 のロールの差分が「意図した変更」だけ。fox の zabbix_money_market の失敗は波 2 で直すので、ここでは除く

- [ ] **Step 4: 承認を得て反映する**

差分をユーザーに見せ、承認を得てから、波 1 のロールのタグで 5 台に反映する。

- [ ] **Step 5: 2 回目を流す**

Expected: 波 1 のロールのタスクがすべて `changed=0`。fox で `/srv/matter_server/data/*.json` があり、`/srv/matter-server` がなく、HA の Matter のエンティティが available（`mcporter call home-assistant.<tool>` で確かめる）

- [ ] **Step 6: main にマージする**

`git merge --ff-only refactor/role-migration-wave1`、push、CI の Ansible Lint、Gitleaks、Push on main が success
