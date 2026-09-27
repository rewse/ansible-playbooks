# 既存ロールの移行 波 3（格上げと OS ロール）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 次のロールを格上げする。
- fail2ban、network_failover、php_miio、restic、nix、builder_toolbox

あわせて次のことを行う。
- darwin/personal と darwin/business を解体する
- Claude Code を darwin_business 以外から消す
- ubuntu、raspberrypi、darwin をコンポーネントのファイルに分ける
- playbook のロールをアルファベット順に並べる

**Architecture:** 格上げは `git mv` とタスクの移動で進め、ユニット名と設定のパスは今のまま引き継ぐ。種別ごとの違いは inventory の `group_vars/<group>/<role>.yml` に移す。OS ロールの分割は、波 1 と同じく `tasks/main.yml` を `import_tasks` だけにする形で行う。

**Tech Stack:** ansible-core、ansible-lint（pre-commit 経由）、pytest、chezmoi

**Spec:** `docs/superpowers/specs/2026-09-27-role-migration-design.md`

## Global Constraints

- ブランチは `refactor/role-migration-wave3`。ロールごとにコミットする
- 波 1 の Global Constraints（コンポーネントの形、タグ、handler の名前と本体）をそのまま守る。同じ名前の handler がほかのロールにもあって、順番が大事なときは、`<role> : <handler>` の名前で notify する（波 2 のレビューの Important）
- **AGENTS.md の Running Playbooks に従う。** check と反映は、変えたロールやコンポーネントのタグで絞る。playbook 全体を流すのは Task 9 の最後の確認だけにする
- darwin_business の Mac では検証しない。変えるのは置き場所と命名だけにする。ただし `claude-code` を toolbox の一覧に足すことだけは例外にする
- 意図した変更（check の差分に出てよいもの）は次のとおり
  - Claude Code と `~/.claude` の削除
  - fail2ban の jail の置き場所は変えないこと（ファイルのパスは同じ）
  - hotel の `/srv/php-miio-v.0.2.6` と `/srv/monitor`、3 台の `/srv/git`（中身を確かめてから消す）
  - youth の `mas` がパスワードを求めなくなること
  - npm のグローバルパッケージが毎回入れ直されなくなること
- chezmoi のリポジトリの変更は、差分を見せて承認をもらってから push する

## Review Focus

- restic の統合で、systemd や launchd のユニット名、リポジトリのパス、パスワードの置き場所が変わると、バックアップが止まったり、新しいリポジトリができたりする。Task 4 で `systemctl list-timers 'restic-*'` と `launchctl list | grep restic` を反映の前後で比べる
- nas は restic の S3 のユニットがあることを前提にしてる。アルファベット順に並べると nas が restic より先になるから、`nas` の meta で `restic` に依存させる
- fail2ban の jail をサービスのロールに移すと、ログのないホストで jail が有効になって、reload のたびに警告が出る。今の「ログがあるときだけ有効にする」条件をそのまま引き継ぐ
- `~/.claude` の削除より先に chezmoi の変更が入らないと、次の `chezmoi apply` でまた作られる。Task 1 の push を Task 6 と Task 7 の反映より先に済ませる
- darwin_business の inventory の一覧を移し間違えると、業務用のアプリが消えるか、入らなくなる。Task 7 で、移す前と後の一覧を `diff` で比べる（今の一覧を順番以外そのまま残す）

---

### Task 1: chezmoi で `.claude` を業務用の Mac だけに配る

**Files:** `~/.local/share/chezmoi/.chezmoiignore`

- `{{- if ne .chezmoi.hostname "7cf34ded5d65" }}` の中に `.claude` と `.claude.json` を足す
- [ ] **Step 1:** `chezmoi --no-pager diff` を youth で流す。Expected: `.claude` の管理から外れる以外の差分がない
- [ ] **Step 2:** 差分をユーザーに見せて、承認をもらってから commit と push をする

### Task 2: `fail2ban` ロール

**Files:** 作る：`roles/fail2ban/`。変える：`roles/ubuntu`、`roles/couchdb`、`roles/zabbix_server`、`roles/homeassistant`、3 つの playbook

| ロール | 中身 |
|---|---|
| fail2ban | `package`（fail2ban を ubuntu のパッケージ一覧から移す）、`config`（jail.local と sshd の jail）。handler は `Restart fail2ban` |
| couchdb、zabbix_server、homeassistant | `fail2ban` コンポーネント（filter と、ログがあるときだけ有効にする jail）。meta で `fail2ban` に依存させる |

- ログの stat と `ubuntu_*_log` の set_fact をなくして、それぞれのロールで自分のログを stat する
- homeassistant は、`tasks/main.yml` に `import_tasks: fail2ban.yml` の 1 行を足すだけにする（ほかの移行は波 4 で行う）
- [ ] **Step 1:** lint と、`--check --diff --tags fail2ban,couchdb_fail2ban,zabbix_server_fail2ban,homeassistant_fail2ban`（fox、hotel、alfa）。Expected: exit 0、`changed=0`
- [ ] **Step 2:** ロールごとにコミットする

### Task 3: `network_failover` と `php_miio`

- network_failover：raspberrypi の `network-failover` の 5 タスク、テンプレート、files、timer の handler を移す。`raspberrypi_primary_address` などの変数は、使うロールの接頭辞に合わせて改名する
- php_miio：checkout だけにする（`/opt/php-miio`、`update` タグ）。`/srv/php-miio` と `/srv/php-miio-v.0.2.6` を消す
- raspberrypi の meta は使わずに、home 系の 2 つの playbook のサービスの層に足す
- [ ] **Step 1:** lint と、fox、hotel で `--check --diff --tags network_failover,php_miio`。Expected: exit 0。changed は古いディレクトリの削除だけ
- [ ] **Step 2:** コミットする

### Task 4: `restic` の統合

**Files:** `git mv roles/restic-darwin roles/restic`、raspberrypi の backup の 28 タスクと files、templates、handlers、`tests/test_restic_darwin_templates.py`

| コンポーネント | 中身 |
|---|---|
| `set_vars`（`always`） | `vars/{{ ansible_facts['system'] \| lower }}.yml` を読む |
| `binary` | Linux は aged_release の Release、macOS は Homebrew（`update` タグ） |
| `linux` と `darwin` | `include_tasks` で OS ごとに切り替える（`apply.tags` を付ける） |

- 変数：`raspberrypi_backup`、`raspberrypi_restic`、`restic_darwin` を、`restic_*` の平らな名前にする（例：`restic_s3_bucket`）。OS ごとに違う値は `vars/linux.yml` と `vars/darwin.yml` に置く
- ユニット名（`restic-local-backup@<host>` など）、launchd のラベル（`jp.rewse.restic-s3-*`）、パスワードと鍵のパスは変えない
- `roles/nas/meta/main.yml` で `restic` に依存させる
- テストのパスと変数名を新しいロールに合わせる。まず失敗させて、そのあと通す
- [ ] **Step 1:** pytest が失敗することを確かめ（RED）、移行したあとで通ることを確かめる（GREEN）
- [ ] **Step 2:** lint と、fox、hotel、youth で `--check --diff --tags restic`。Expected: exit 0。差分は、テンプレートのヘッダーだけ
- [ ] **Step 3:** 反映の前に、`systemctl list-timers 'restic-*'` と `launchctl list | grep restic` の出力を記録しておく
- [ ] **Step 4:** コミットする

### Task 5: ubuntu の分割

コンポーネント（ファイル）は次のとおり。`upgrade` は最後に置き、`update` タグを付ける。

- `facts`（`always`）
- `timezone`、`github`、`onepassword`、`nodejs`、`package`、`awscliv2`、`kiro_cli`、`uv`、`zinit`、`etckeeper`、`hostname`、`inputrc`、`user`、`ssh`、`failure_notify`、`ghostty`、`skills`、`agent_browser`、`lightpanda`、`npm`
- `upgrade`

- 1Password の debsig ポリシーと GitHub の GPG キー：今は毎回 changed になってる。`/usr/local/src` などの永続する場所に置くか、`uri` と `copy` の形にして、中身が変わったときだけ changed にする
- `npm`：今は `npm update -g` が毎回 20 パッケージを入れ直してる。まず原因を調べて、パッケージが古いときだけ更新するようにする（例：`npm outdated -g --json` の結果で決める）。agent-browser の実行権は、入れ直したときだけ付け直す。原因を調べた結果はコミットメッセージに書く
- 変数とレジスタの接頭辞を `ubuntu_` と `__ubuntu_` にそろえる
- [ ] **Step 1:** lint と、3 台で `--check --diff --tags ubuntu`。Expected: exit 0。changed は、鍵の置き場所の初回の移動だけ
- [ ] **Step 2:** コミットする

### Task 6: raspberrypi の分割と Claude Code の削除

コンポーネント：`package`、`swap`、`ntp`、`journald`、`bluetooth`、`snmp`、`environment`、`nvme`（boot の設定を含む）、`network`（netplan、cloud-init、sysctl、適用と到達の待ち）、`ssh`、`qwen_code`、`claude_code`

- `claude_code`：インストールと更新をやめて、`/root/.local/bin/claude`、`/root/.local/share/claude`、`/root/.claude`、`/root/.claude.json`、`/usr/local/bin/claude`、`/home/{{ admin }}/.claude`、`/home/{{ admin }}/.claude.json` を消す（legacy-removal）
- [ ] **Step 1:** lint と、fox、hotel で `--check --diff --tags raspberrypi`。Expected: exit 0。changed は Claude Code の削除だけ
- [ ] **Step 2:** コミットする

### Task 7: darwin の解体と分割

- `inventory/group_vars/darwin_personal/darwin.yml` と `inventory/group_vars/darwin_business/darwin.yml` を作る。中身は `darwin_extra_packages`、`darwin_extra_casks`、`darwin_extra_mas_apps`。treefmt は personal の `darwin_extra_packages` に入れる
- `roles/nix`：darwin/personal の nix の 7 タスクを移す（`update` タグ）
- `roles/builder_toolbox`：toolbox、enfable、Kiro IDE、aim を移す。`toolbox install` の一覧に `claude-code` を足す
- darwin のコンポーネント：`tap`、`package`、`cask`、`mas`、`npm`、`uv`、`font`、`security`、`path`、`xurl`、`upgrade`
  - `mas`：`community.general.mas` で、もう入ってるかを先に確かめる。入ってないアプリだけに become を使う。こうすると、2 回目からはパスワードを求めなくなる
- Claude Code：`darwin_legacy_paths`（既定は `[]`）を darwin_personal の group_vars に書いて、darwin の `cleanup` コンポーネントで消す。対象は `~/.local/bin/claude`、`~/.local/share/claude`、`~/.claude`、`~/.claude.json`
- 2 つの darwin の playbook に、play の名前とロールのタグを付ける
- [ ] **Step 1:** personal と business のパッケージの一覧を、移す前と後で `diff` にかける。Expected: 順番以外の差分がない
- [ ] **Step 2:** lint、`darwin-business.yml --syntax-check`、youth で `--check --diff --tags darwin,nix`。Expected: exit 0。changed は Claude Code の削除と Homebrew の更新だけ
- [ ] **Step 3:** ロールごとにコミットする

### Task 8: playbook の並べ替えと文書

- 3 つの Ubuntu の playbook を層ごとに並べる（OS → プラットフォーム → OS をまたぐツール → サービス）。層の中はアルファベット順にする
- 並べ替えで順番が変わって困るものは、meta の依存で表す
- `--list-tasks` で、ロールの並び順を移す前と後で比べる
- 規約を変えたところを AGENTS.md に反映する：同じ名前の handler は `<role> : <handler>` で notify すること、`darwin_extra_*` の例、`restic` の OS の分け方。README の構成図も直す
- [ ] **Step 1:** lint、全 playbook の `--syntax-check`、`.ansible-lint-ignore` の残りの行（homeassistant、nas、tests の分だけ）
- [ ] **Step 2:** コミットする

### Task 9: 検証とマージ

- [ ] **Step 1:** 4 台で playbook 全体を `--check --diff` で流す（変更をまとめて最後に確かめるため）。Expected: exit 0（youth の mas も含む）
- [ ] **Step 2:** 差分をユーザーに見せて承認をもらい、波 3 で変えたロールのタグで反映する
- [ ] **Step 3:** 同じタグで 2 回目を流す。Expected: `changed=0`
  - restic のタイマーが、Task 4 の Step 3 で記録したものと同じ
  - fail2ban の jail が全部 active
  - Claude Code が fox、hotel、youth にない
- [ ] **Step 4:** main に fast-forward でマージして、CI が通るのを確かめる。business の Mac で確かめる手順（`ansible-playbook darwin-business.yml --check --diff`、そのあと反映、`toolbox list` に `claude-code` があるか）を完了報告に書く
