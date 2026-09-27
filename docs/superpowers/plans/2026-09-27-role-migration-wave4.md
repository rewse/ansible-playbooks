# 既存ロールの移行 波 4（大きいサービス）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** nas と homeassistant をコンポーネントのファイルに分けて lint を通し、収束した legacy-removal と `.ansible-lint-ignore` を消して、spec の完了条件を満たす。

**Architecture:** 波 1〜3 と同じく、`tasks/main.yml` を `import_tasks` だけにして、タスクは中身を変えずにコンポーネントのファイルへ移す。homeassistant の `configuration.yaml` の編集は順番に依存するので、1 つのコンポーネントにまとめて今の順番を保つ。最後に 5 台で playbook 全体を 2 回流して、完了条件を確かめる。

**Tech Stack:** ansible-core、ansible-lint（pre-commit 経由）、pytest

**Spec:** `docs/superpowers/specs/2026-09-27-role-migration-design.md`

## Global Constraints

- ブランチは `refactor/role-migration-wave4`。ロールごとにコミットする
- 波 1〜3 の Global Constraints（コンポーネントの形、タグ、handler の名前と本体、role-qualified notify）をそのまま守る
- `roles/homeassistant/files/` には触らない。HA の「Copy default file」と、それが `configuration.yaml` を戻すことで毎回 changed になる include の lineinfile は、HA YAML セッションで直すので残す
- `roles/homeassistant/tests/` は `.ansible-lint-ignore` にあるファイルの lint だけを直す。`model_y_full_charge_due.yml` には触らない。テストは `../vars/main.yml`、`../templates/secrets.yaml.j2`、`../files/` を読むので、`vars/main.yml` の変数名と `secrets.yaml.j2` の名前は変えない
- check と反映は、変えたロールのタグで絞る。playbook 全体を流すのは Task 6 だけにする
- 反映の前に `--check --diff` の要約を見せて承認をもらう
- 意図した変更（check の差分に出てよいもの）は次のとおり
  - nas のテンプレートに足す `ansible_managed` のヘッダーと、それに伴う `daemon-reload`
  - 収束した legacy-removal タスクと `fail2ban_legacy_jails` の削除（ホストには何も起きない）
  - homeassistant の `secrets.yaml` と `shell_commands.yaml` に足すヘッダーと、それに伴う Home Assistant の 1 回の再起動

## Review Focus

- homeassistant の handler を `Restart Home Assistant` などに改名すると、古い名前で notify してるタスクが残ったときに `The requested handler ... was not found` で止まる。Task 2 と 3 で、全ロールの notify の文字列がどれかの handler 名と一致することを確かめる
- `configuration.yaml` の include は `insertafter` で前の行を足場にしてる。順番が変わると、行が別の場所に入って差分が出る。Task 2 で、移す前と後の lineinfile の順番を `--list-tasks` で比べる
- カスタムコンポーネントは、check mode で checkout がまだないときに install を飛ばして理由を報告してる。コンポーネントに分けても、`--tags homeassistant_<comp>` 単独の check が exit 0 になること
- nas の handler は `Restart avahi-daemon` が `Restart smbd` より先に定義されてることで順番が決まってる。分けても handlers の順を保つ
- `--tags nas_s3` 単独で流しても、restic の S3 のユニットがあることの assert が drop-in より先に走ること

---

### Task 1: nas の分割

**Files:** 変える：`roles/nas/tasks/main.yml`、`roles/nas/handlers/main.yml`、`roles/nas/templates/*.j2`。作る：`roles/nas/tasks/{storage,nfs,samba,zabbix,s3}.yml`

| コンポーネント | 中身（今のタスク） |
|---|---|
| `storage` | key directory、LUKS key file、mount points、crypttab、fstab、udev、attach と detach のスクリプト、attach unit とその有効化、Docker の override |
| `nfs` | NFS server のインストール、export ディレクトリ、exports、NFS server の有効化 |
| `samba` | Samba のインストール、サービスユーザー、home、Time Machine のディレクトリ、Avahi、smb.conf、pdbedit、Samba ユーザー、smbd の有効化 |
| `zabbix` | Zabbix agent の設定（今の `nas_monitor` タグ） |
| `s3` | restic の S3 ユニットの stat と assert、drop-in、スケジュール、timer の有効化 |

- タグは `nas_storage`、`nas_nfs`、`nas_samba`、`nas_zabbix`、`nas_s3` にする。`luks`、`storage`、`config`、`install` などの操作タグはなくす
- handler は `Reload exports`、`Reload systemd`、`Reload udev rules`、`Restart zabbix-agent`、`Restart avahi-daemon`、`Restart smbd` にして、今の順番を保つ。`Reload systemd` はほかのロールにもあるので `nas : Reload systemd` で notify する
- register は `__nas_pdbedit`、`__nas_s3_template` にする
- 「Create Samba users」の command に理由のコメントと `changed_when: true` を足す（ユーザーがないときだけ走る）
- ヘッダーのないテンプレート（`docker-nas-mounts.conf.j2`、`nas-attach.j2`、`nas-attach.service.j2`、`nas-backup-s3-schedule.conf.j2`、`nas-detach.j2`、`restic-s3-source.conf.j2`、`restic-timer-schedule.conf.j2`）に `{{ ansible_managed | comment }}` を足す。シェルスクリプトは shebang の次の行に置く。`exports.j2` と `smb.conf.j2` の `# {{ ansible_managed }}` は `{{ ansible_managed | comment }}` にそろえる
- [ ] **Step 1:** `.ansible-lint-ignore` から `roles/nas/` の行を消して、`ansible-lint roles/nas`。Expected: failure 0
- [ ] **Step 2:** fox で `--check --diff --tags nas`、つづけて `--tags nas_s3` 単独。Expected: exit 0。差分はヘッダーだけ
- [ ] **Step 3:** コミットする

### Task 2: homeassistant の基本部分の分割

**Files:** 変える：`roles/homeassistant/{tasks/main.yml,handlers/main.yml}`、`roles/homeassistant_ha_secondary/tasks/apache.yml`。作る：`roles/homeassistant/tasks/{package,certs,container,apparmor,configuration,automation,tesla_fleet,apache}.yml`

| コンポーネント | 中身（今のタスク） |
|---|---|
| `package` | apparmor-utils |
| `certs` | certs ディレクトリ、ルート証明書 |
| `container` | イメージの解決、compose ディレクトリ、compose ファイル、check mode の報告、起動（`update` タグ） |
| `apparmor` | docker-default のダウンロード、無効化サービス |
| `configuration` | Copy default file、secrets、全部の include と設定ファイルのコピー（今の順番のまま）、customize、main settings |
| `automation` | automations と blueprints のディレクトリ、automation ファイルのコピー。include の行は `configuration` に残す（ほかの include の足場なので） |
| `tesla_fleet` | 秘密鍵、公開鍵のディレクトリと公開鍵 |
| `apache` | proxy モジュール、vhost、a2ensite |

- `configuration` のタスク名は `configuration | Copy default file`、`configuration | Configure <domain> include`、`configuration | Copy <domain> configuration` にする。notify の有無は今のタスクのとおりにする（input_* と scene と script は notify しない）
- handler は次のとおりに改名し、notify もそろえる
  - `homeassistant: Restart` → `Restart Home Assistant`
  - `aa-disable-homeassistant: Restart` → `Restart aa-disable-homeassistant`
  - `apache: Reload` → `Reload Apache`、`apache: Restart` → `Restart Apache`（httpd と同じ本体）
- register は `__homeassistant_a2ensite` にする。a2ensite の command に理由のコメントを足す
- `secrets.yaml.j2` と `shell_commands.yaml.j2` の先頭に `[% ansible_managed | comment %]` を足す（この 2 つは `variable_start_string: "[%"` で描画するため）。足したあと、Task 4 の Step 1 の 9 本のテストが通ることを確かめる
- `homeassistant_ha_secondary/tasks/apache.yml` の `{{ playbook_dir }}/roles/homeassistant/` を `{{ role_path }}/../homeassistant/` にする
- [ ] **Step 1:** 移す前に `--list-tasks --tags homeassistant` を fox で記録し、移したあとと比べる。Expected: `configuration` の lineinfile の順番が同じ
- [ ] **Step 2:** notify の文字列の一覧と handler 名の一覧を全ロールから取り出して比べる。Expected: 見つからない notify がない
- [ ] **Step 3:** fox で `--check --diff --tags homeassistant`、hotel で `--tags homeassistant_ha_secondary`。Expected: exit 0。changed は Copy default file と include、2 つのヘッダーと再起動の handler だけ
- [ ] **Step 4:** コミットする

### Task 3: homeassistant のカスタムコンポーネントと Lovelace の分割

**Files:** 変える：`roles/homeassistant/tasks/main.yml`。作る：`roles/homeassistant/tasks/{frigate,echonet_lite,tuya,frosted_glass,card_mod,mini_graph_card,mini_media_player,simple_weather_card}.yml`

- どれも `update` タグを付け、`custom_components`、`themes`、`www` のうち使うディレクトリの作成を自分のファイルに持つ（タグ単独で流せるように）
- `frosted_glass` は manager と themes の両方を持つ
- echonet_lite の register は `__homeassistant_echonet_lite_{git,clean,sync}` にする。`# noqa command-instead-of-module` は理由のコメントに置き換える（rsync の `--delete` 付き同期に使える module がない）
- 「Remove legacy checkout」の 6 タスクは、fox でパスがないことを `test -e` で確かめて消す。残っていたら、そのコンポーネントの最後に残す
- [ ] **Step 1:** fox で `--check --diff --tags homeassistant_frigate`、同じく echonet_lite、tuya、frosted_glass、card_mod を 1 つずつ。Expected: どれも exit 0
- [ ] **Step 2:** `.ansible-lint-ignore` から `roles/homeassistant/{handlers,tasks}` の行を消して、`ansible-lint roles/homeassistant`。Expected: tests 以外の failure 0
- [ ] **Step 3:** コミットする

### Task 4: homeassistant のテストの lint

**Files:** 変える：`.ansible-lint-ignore` にある `roles/homeassistant/tests/*.yml`

- `name[casing]`：`"zone-test : Read configuration"` のような名前を `Read configuration` にする（play 名と接頭辞で区別できるので接頭辞はなくす）
- `name[prefix]`：include される `*_room.yml` のタスク名から接頭辞をなくし、Jinja は名前の最後に置く
- `var-naming[no-role-prefix]`：`*_room.yml` で set_fact する変数に `homeassistant_` の接頭辞を付け、呼び出し側もそろえる
- [ ] **Step 1:** 直す前に、`_room.yml` 以外の 9 本を `ansible-playbook roles/homeassistant/tests/<name>.yml` で流す。Expected: どれも exit 0（記録済みの基準）
- [ ] **Step 2:** 直したあと同じ 9 本を流す。Expected: どれも exit 0
- [ ] **Step 3:** `ansible-lint roles/homeassistant`。Expected: failure 0
- [ ] **Step 4:** コミットする

### Task 5: 収束した後片付けと文書

**Files:** 消す：`.ansible-lint-ignore`、`inventory/host_vars/{alfa,hotel}.rewse.jp/fail2ban.yml`。変える：legacy-removal のあるタスクファイル、`roles/fail2ban/{tasks/config.yml,defaults/main.yml}`、`AGENTS.md`、`README.md`

- `rg 'state: absent' roles` の結果を 1 つずつ見て、以前の状態を消すためだけのタスクで、対象のホストすべてでパスがないものを消す。対象は Claude Code（ubuntu の `claude_code` と darwin の `darwin_legacy_paths`）、php_miio の古いディレクトリ、fail2ban の legacy jail、NodeSource の古いリストなど。業務用の Mac で走るタスク（darwin の共通部分、builder_toolbox）は確かめられないので残す。毎回の状態を保つためのタスク（restic の古いアーカイブ、httpd の default site など）は残す
- `fail2ban` の「Remove jails for services this host does not run」と `fail2ban_legacy_jails` を消す
- AGENTS.md の Ansible Conventions の冒頭から `.ansible-lint-ignore` の文を消し、Lint の「Do not add entries to `.ansible-lint-ignore`」を「Do not create `.ansible-lint-ignore`; fix the violation or use a `# noqa` with a reason」にする
- README のプロジェクト構成が今のファイルと合ってるか確かめる
- [ ] **Step 1:** pre-commit を全ファイルに流す。Expected: 全部 Passed
- [ ] **Step 2:** 消したタスクのあるロールを、そのロールのタグで check する。Expected: exit 0、`changed=0`
- [ ] **Step 3:** コミットする

### Task 6: 完了条件の確認とマージ

- [ ] **Step 1:** fox、hotel、alfa、youth、sierra で、各 playbook 全体を `--check --diff` で流す（タグで絞らない）。Expected: どれも exit 0
- [ ] **Step 2:** 差分の要約をユーザーに見せて、承認をもらってから playbook 全体を反映する
- [ ] **Step 3:** 同じく 2 回目を流す。Expected: `changed=0`。例外は homeassistant の Copy default file と、それに続く include の lineinfile だけ
- [ ] **Step 4:** 最後のレビューを受け、Critical と Important を直す。main に fast-forward でマージして、CI が通るのを確かめる。spec の完了条件 5 つを 1 つずつ根拠付きで報告する
