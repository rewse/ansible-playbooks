# 既存ロールの移行 波 2（フラット化と統合）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ネストした 12 ロールを、フラットな名前の 10 ロールにする。`zabbix/agent/*` は `zabbix_agent` にまとめる。あわせて、毎回 changed になるタスクと check mode の失敗を直し、orascript と stock-price-fetcher を `/opt` に移す。

**Architecture:** `git mv` でロールを移し、波 1 と同じ形（`tasks/main.yml` には `import_tasks` だけ）に分ける。playbook、`meta` の依存、inventory を新しい名前に合わせる。改名と分割ではホストの状態を変えない。check の差分は、下の「意図した変更」だけになるはずである。

**Tech Stack:** ansible-core、ansible-lint（pre-commit 経由）

**Spec:** `docs/superpowers/specs/2026-09-27-role-migration-design.md`

## Global Constraints

- ブランチは `refactor/role-migration-wave2`。ロールごとに Conventional Commits でコミットする
- 波 1 の Global Constraints（コンポーネントの形、タグ、handler 名と同名の handler の本体、ignore の行の削除）をそのまま守る
- playbook のロールのタグ（`database_client`、`database_client_gui`、`homeassistant_ha_primary`、`homeassistant_ha_secondary`、`postfix_client`、`zabbix_agent`、`zabbix_aws`、`zabbix_mcp`、`zabbix_money_market`、`zabbix_server`）は、サブプロジェクト 2 で付けたものから変えない
- 変数はロール名で始める。例：`zabbix_agent`→`zabbix_agent_server`、`database_corretto_version`→`database_client_gui_corretto_version`、`postfix_relayhost`→`postfix_client_relayhost`
- 収束済みの legacy-removal タスクを消す。全ホストで対象がないことを確かめてあるのは次の 5 つ：`/etc/zabbix/zabbix_agentd.conf.d`、`userparameter_mysql.conf`、`/usr/local/bin/cloudwatch`、`/srv/git/ssl-cert-check`、`/etc/apt/sources.list.d/corretto.list`（corretto は alfa で確かめる）
- 波 2 が終わると、`apache: Reload` と `apache: Restart` を定義せずに通知するロールはなくなる。そこで httpd の handler の `listen` を消す
- 意図した変更（check の差分に出てよいもの）は次だけである
  - fox、hotel の zabbix-agent を、ユニットのコピーから drop-in に切り替えること
  - orascript と stock-price-fetcher を `/opt` に移すこと
  - alfa の古い Redshift の jar と、古い `instantclient_*` を消すこと
  - corretto の鍵の置き場所
  - SASL の db の touch をやめること
- ホストへの反映は Task 7 でまとめて行い、`--check --diff` の差分を見せて承認を得てからにする

## Review Focus

- zabbix-agent が root で動き続ける。drop-in の `User=root` と `Group=root` と、`AllowRoot=1` がそろっていること。Task 1 で `systemctl show zabbix-agent -p User` を確かめる
- `zabbix_agent_platform` が未定義のホスト（alfa 以外の ubuntu で、将来増えるもの）でも失敗しない。既定値は `ubuntu` にし、`tasks/<platform>.yml` は ubuntu 以外のときだけ読み込む
- 改名で notify の名前が 1 つでも取り残されると、Ansible は handler が見つからないエラーで止まる。Task 7 で、全 playbook の `--syntax-check` と check を流す
- stock-price-fetcher の移動で、Zabbix の外部スクリプトが古いパスを `cd` すると、株価の項目が unsupported になる。Task 2 で `zabbix_get` を使うか、スクリプトを直接実行して確かめる
- `~/oracle` のリンクの先が変わっても、`~/.orarc` から SQL が読める。Task 4 で `ls ~/oracle/` を確かめる

---

### Task 1: `zabbix_agent` への統合

**Files:**
- Create: `roles/zabbix_agent/`（`git mv roles/zabbix/agent/ubuntu roles/zabbix_agent` のあと、raspberrypi と ec2 の `files/` を移す）
- Modify: 3 つの playbook、`roles/zabbix/aws/meta/main.yml`
- Create: `inventory/host_vars/{fox,hotel,alfa}.rewse.jp/zabbix_agent.yml`（`zabbix_agent_platform: raspberrypi` か `ec2`）

| コンポーネント | 中身 |
|---|---|
| `package` | zabbix-release、パッケージ、zabbix ユーザーを adm グループに入れる |
| `config` | Server、ServerActive、Hostname、Timeout、Include の行、設定ディレクトリ、Ubuntu の設定、agentscripts、sudo の設定 |
| `platform` | `include_tasks: "{{ zabbix_agent_platform }}.yml"`（`apply.tags` にロール名とコンポーネントのタグを入れる）。`when: zabbix_agent_platform != 'ubuntu'` |

- `defaults/main.yml` に `zabbix_agent_platform: ubuntu` を置く
- `tasks/raspberrypi.yml` では、ユニットのコピーと `User`、`Group` の lineinfile をやめる。代わりに `/etc/systemd/system/zabbix-agent.service.d/override.conf`（`[Service]` に `User=root` と `Group=root`）を template で置いて、`Reload systemd` と `Restart zabbix-agent` を通知する。あわせて `/etc/systemd/system/zabbix-agent.service` を消す。AllowRoot と Bluetooth の設定は今のままにする
- `tasks/ec2.yml` は、監視のスクリプトと設定を置くだけにする
- handler は `Reload systemd` と `Restart zabbix-agent` にする（波 1 と同じ本体）
- playbook の 2 行（`zabbix/agent/ubuntu` と `zabbix/agent/<platform>`）を、`zabbix_agent` の 1 行にまとめる
- `roles/zabbix/aws/meta/main.yml` の `{role: zabbix/agent}`（存在しないロール名）を、タグ付きの `zabbix_agent` にする

- [ ] **Step 1: 移して分割し、lint を通す**

Run: `ansible-lint --nocolor roles/zabbix_agent home-primary.yml home-secondary.yml cloud-workstation.yml`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: 3 台で `--check --diff --tags zabbix_agent`
Expected: exit 0。fox と hotel では、drop-in の作成、ユニットのコピーの削除、`Reload systemd`、`Restart zabbix-agent` だけが changed。alfa は `changed=0`

- [ ] **Step 3: コミット**

`refactor(zabbix_agent): merge the platform agent roles into one`

### Task 2: `zabbix_server`、`zabbix_aws`、`zabbix_mcp`、`zabbix_money_market`

| ロール | コンポーネント | 補足 |
|---|---|---|
| zabbix_server | `package`、`server`（systemd の override と、zabbix_server.conf の行）、`frontend`、`ssl_cert_check` | `ssl_cert_check` は `update` タグ。handler は `Restart zabbix-server`、`Reload Apache`、`Restart Apache` |
| zabbix_aws | `guardduty` | meta は `zabbix_agent` |
| zabbix_mcp | `user`、`app`（tag の解決、checkout、venv、install）、`service` | `app` は `update` タグ。handler は `Reload systemd`、`Restart zabbix-mcp-server` |
| zabbix_money_market | `app`、`script` | 下の方式にする。`app` は `update` タグ |

zabbix_money_market の `app`:
- 置き場所を `/opt/stock-price-fetcher` にする（AGENTS.md の「checkout から動くものは `/opt`」）。`files/stock-price-fetcher.sh` の `cd` の先も合わせる
- git モジュールは、今と同じ root と admin の鍵で `version: main` を checkout する。先に `community.general.git_config` で root の `safe.directory` に登録しておく。そのあと `file: recurse: true` で `zabbix:zabbix` にする
- 古い `/usr/lib/zabbix/stock-price-fetcher` を消す（legacy-removal）
- `uv sync` は自分のリポジトリで lockfile があるから、cooldown の対象外にする（AGENTS.md のとおり）。`changed_when` は、`uv sync` の stderr に `Installed` か `Uninstalled` があるときにする

- [ ] **Step 1: 移して分割し、lint を通す**

Run: `ansible-lint --nocolor roles/zabbix_server roles/zabbix_aws roles/zabbix_mcp roles/zabbix_money_market`
Expected: `Passed: 0 failure(s)`

- [ ] **Step 2: check を確かめる**

Run: `home-primary.yml --check --diff --tags zabbix_server,zabbix_mcp,zabbix_money_market`、`cloud-workstation.yml --check --diff --tags zabbix_aws`
Expected: exit 0（money-market の clone の失敗がなくなる）。changed は、money-market の新しい checkout、所有者、古い場所の削除、スクリプトだけ

- [ ] **Step 3: ロールごとにコミット**

### Task 3: `postfix_client`

| コンポーネント | 中身 |
|---|---|
| `main_cf` | myhostname から smtp_tls_wrappermode までの 7 行と、sender_canonical_maps の行 |
| `sasl` | SASL の 4 行と、パスワードファイル |
| `sender_canonical` | sender_canonical のファイル |
| `aliases` | root の alias |

- `Create SASL password database file`（毎回 touch するタスク）は消す。db はパスワードファイルが変わったときに、handler `Hash SASL password file`（postmap）が作る
- handler は `Hash SASL password file`、`Hash sender_canonical`、`Rebuild aliases`、`Reload postfix`

- [ ] **Step 1: 移して分割し、lint と check を通す**

Run: `ansible-lint --nocolor roles/postfix_client`、3 台で `--check --diff --tags postfix_client`
Expected: lint は 0 件。check は exit 0 で `changed=0`

- [ ] **Step 2: コミット**

### Task 4: `database_client`

| コンポーネント | 中身 |
|---|---|
| `mysql` | apt 設定のパッケージ、パッケージ、connector-j |
| `oracle` | instantclient の取得と展開、ディレクトリの選択、PATH、ld.so.conf、ojdbc のリンク |
| `orascript` | checkout、`.orarc`、`~/oracle` のリンク |
| `redshift` | release の解決、jar、リンク |

`oracle`、`redshift`、`orascript` は `update` タグ。

- instantclient：3 つの zip ごとに `uri: method: HEAD`（`check_mode: false`）で `ETag` を読み、`/usr/local/src/instantclient-<name>.etag` と比べる。違うときだけ `get_url`（`force: true`）と `unarchive` を流して、そのあとで ETag を書く。新しいホストで `instantclient_*` がまだないときも展開する（`matched == 0`）。check mode でディレクトリがないときは、選択のタスクと、それを使うタスクを飛ばす
- 一番新しいもの以外の `/srv/instantclient_*` を消す
- Redshift：`get_url` の `dest` をファイル名まで書く（ディレクトリを指定すると check mode で毎回 changed になるため）。リンク先以外の `redshift-jdbc42-*.jar` を消す
- orascript：`/opt/orascript` を admin の所有で作る。git を `become_user: admin` で checkout して、所有者のタスクと `safe.directory` をなくす。`~/oracle` を `/opt/orascript/common` に向ける。`/srv/git/orascript` を消す

- [ ] **Step 1: 移して分割し、lint と check を通す**

Run: `ansible-lint --nocolor roles/database_client`、`cloud-workstation.yml --check --diff --tags database_client`
Expected: lint は 0 件。check は exit 0。changed は orascript の移動と、古い instantclient と jar の削除、初回の ETag の記録だけ

- [ ] **Step 2: コミット**

### Task 5: `database_client_gui`

| コンポーネント | 中身 |
|---|---|
| `corretto` | repo と JDK |
| `sct` | 取得、展開、パッケージ |
| `dbeaver` | パッケージ |

`corretto`、`sct`、`dbeaver` は `update` タグ。

- corretto：`deb822_repository` の `signed_by` に鍵の URL（`https://apt.corretto.aws/corretto.key`）を渡す。gpg の dearmor、鍵のダウンロード、`python3-debian` の `update_cache`、`Update apt cache` をやめる。JDK の `apt` に `update_cache: true` を付ける。古い `/etc/apt/keyrings/corretto.{key,gpg}` と legacy の list を消す
- `database_corretto_version` は `database_client_gui_corretto_version` にする（コメントはそのまま残す）

- [ ] **Step 1: 移して分割し、lint と check を通す**

Run: `ansible-lint --nocolor roles/database_client_gui`、`cloud-workstation.yml --check --diff --tags database_client_gui`
Expected: exit 0。changed は corretto の鍵の置き場所と、古い鍵の削除だけ

- [ ] **Step 2: コミット**

### Task 6: `homeassistant_ha_primary` と `homeassistant_ha_secondary`

| ロール | コンポーネント |
|---|---|
| primary | `rsync`、`zabbix` |
| secondary | `rsync`、`container`（`update`）、`failover`、`failback`、`name_switch`、`sslcert`、`apache`、`zabbix` |

- handler は `Restart rsync`、`Restart zabbix-agent`、`Reload systemd`、`Reload Apache`、`Restart Apache`。secondary は Apache の handler を自分で定義する
- httpd の handler から `listen` を消す
- `homeassistant_ha_*` の変数と `__` の register を、ロール名の接頭辞に合わせる。どちらのロールでも使う `homeassistant_ha_token` と `homeassistant_ha_standby_ip` は、それぞれ `homeassistant_ha_primary_` と `homeassistant_ha_secondary_` で始める
- `Pull image (standby, do not start)` の `state: stopped` は、今のまま残す（spec の範囲外）

- [ ] **Step 1: 移して分割し、lint と check を通す**

Run: `ansible-lint --nocolor roles/homeassistant_ha_primary roles/homeassistant_ha_secondary roles/httpd`、`home-primary.yml --check --diff --tags homeassistant_ha_primary,httpd`、`home-secondary.yml --check --diff --tags homeassistant_ha_secondary`
Expected: exit 0、`changed=0`

- [ ] **Step 2: ロールごとにコミット**

### Task 7: 波 2 の検証とマージ

- [ ] **Step 1: 全体の lint と構造**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`、全 playbook の `--syntax-check`、`find roles -mindepth 2 -maxdepth 2 -type d -name tasks | awk -F/ 'NF!=3'`
Expected: すべて Passed。ネストしたロールは `darwin/business` と `darwin/personal` だけ（波 3 で解体する）

- [ ] **Step 2: 4 台で check**

Run: fox、hotel、alfa は playbook 全体を `--check --diff` で、youth は `darwin-personal.yml` を流す
Expected: 3 台とも exit 0。差分は「意図した変更」と、波 3 と波 4 の持ち越し（HA の configuration、ubuntu の GPG キー、Homebrew）だけ

- [ ] **Step 3: 承認を得て反映し、2 回目を流す**

Expected: 波 2 のロールは `changed=0`。`systemctl show zabbix-agent -p User` が `User=root` を返す。`/opt/stock-price-fetcher/stock-price-fetcher.sh` 相当の外部スクリプトが値を返す。alfa で `ls ~/oracle/` が SQL を返す

- [ ] **Step 4: main にマージ**

`git merge --ff-only`、push、CI が success
