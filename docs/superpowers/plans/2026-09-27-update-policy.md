# 更新方針の実装 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** lookup プラグイン `aged_release` で cooldown 付きの最新版解決を一本化し、compose をロールごとのプロジェクトに分け、vars の手書きバージョンをなくす。

**Architecture:** コントローラーで動く lookup が skopeo と `gh` を呼び、絞り込み、並べ替え、cooldown の判定をして、digest、sha256、SHA で固定した値を返す。各ロールは `set_fact` で受け取り、`/etc/compose/<role>/compose.yaml`、`/usr/local/src/<name>`、`get_url` に渡す。compose はロールごとに旧プロジェクトから切り替え、最後に共有ファイルと `docker/quarantine` を消す。

**Tech Stack:** ansible-core 2.21.3、Python 3（lookup）、pytest（`uv run --with pytest`）、skopeo、gh、community.docker

**Spec:** `docs/superpowers/specs/2026-09-27-update-policy-design.md`

## Global Constraints

- 作業はブランチ `refactor/update-policy` で行い、最後に main へ fast-forward して push する
- 稼働中のホストへの `--check` なしの実行は、ロールごとに差分を示してユーザーの確認を取ってから行う
- chezmoi リポジトリへの書き込みは、実行前にユーザーの確認を取る
- 各ロールで直すのはバージョン解決、compose、配置のタスクだけ。タスク名、タグ、ファイル分割は変えない。新しく書くタスクは規約に従い、`name[prefix]` に合うよう既存ファイルの書式（`"<component> : <Description>"`）に揃える
- 新しく書くタスクのファイルに `.ansible-lint-ignore` の行を足さない
- lookup の呼び出し: `oci:`、`github-release:`、`github-tag:`、`github-commit:`。戻り値のキーは spec の表のとおり（`version`、`ref`、`url`、`checksum`、`commit`）
- 解決した値は `__<role>_<component>` の名前で `set_fact` する
- `platform` は `linux/{{ 'arm64' if ansible_facts['architecture'] == 'aarch64' else 'amd64' }}`
- 自分のリポジトリのイメージ（`ghcr.io/rewse/...`）は `days=0`
- compose ファイルは `/etc/compose/<role>/compose.yaml`、テンプレートは `compose.yaml.j2`、先頭に `{{ ansible_managed | comment }}` と `name: <role>`
- チェックアウトは `/usr/local/src/<name>`。例外は zabbix_mcp（`/opt/zabbix-mcp/src`）
- playbook の成否はプロセスの終了コードで判断する。実行は `direnv exec .` 経由

## Review Focus

- 旧プロジェクトからの切り替えで、コンテナの削除が新しいプロジェクトのコンテナまで消さないこと。ラベル `com.docker.compose.project` が `etc` のときだけ消す。各ロールの 2 回目の実行で削除タスクが `ok` になることで確かめる
- HA と Matter の `network_mode: host` と、HA が参照する Matter の URL（`ws://localhost:5580`）が切り替え後も通ること。Task 5 の HA のエンティティ確認で確かめる
- lookup が check mode でも同じ値を返し、check と本番で固定の値が変わらないこと。同じ実行内のキャッシュと、check 直後の本番で `ref` や `commit` が同じことを差分で確かめる
- GitHub API の回数制限や認証切れで、実行途中に lookup が失敗したときのメッセージが原因を示すこと。Task 1 の `test_gh_failure_raises` でメッセージに `gh` の stderr が含まれることを確かめる
- `NPM_CONFIG_USERCONFIG` を渡したとき、root で動く Ubuntu と一般ユーザーで動く Mac の両方で、chezmoi の npmrc が読まれること。Task 3 で `npm config get min-release-age` を同じ環境変数付きで両方で確かめる

---

### Task 1: lookup プラグイン `aged_release`

**Files:**
- Create: `plugins/lookup/aged_release.py`
- Create: `tests/test_aged_release.py`
- Modify: `ansible.cfg`（`lookup_plugins = plugins/lookup`）

**Interfaces:**
- Produces:
  - `version_key(tag: str) -> list[int]`
  - `select(candidates: list[dict], pattern: str, days: int, now: datetime) -> dict`。`candidates` は `{"version", "published", ...}` の辞書のリストで、`published` は aware な `datetime`。条件に合うものがなければ `AnsibleLookupError`
  - `resolve(term: str, *, pattern: str, days: int, platform: str | None, asset: str | None, run: Callable[[list[str]], str], now: datetime) -> dict`。`run` は外部コマンドを実行して stdout を返し、失敗時は stderr を含む例外を投げる
  - `LookupModule.run(terms, variables, **kwargs) -> list[dict]`。`days` の既定は `variables['supply_chain_cooldown_days']`。キャッシュはモジュールの辞書で、キーは `(term, pattern, days, platform, asset)`

- [ ] **Step 1: ブランチを作る**

Run: `git switch -c refactor/update-policy`

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_aged_release.py` に次のテストを書く。外部コマンドは `run` に渡す偽関数で、コマンドの引数ごとに用意した JSON を返す。

| テスト名 | 確かめること |
|---|---|
| `test_version_key_orders_numerically` | `2025.10.1` が `2025.6.9` より新しい |
| `test_select_skips_too_new` | 公開 3 日のものを飛ばし、5 日のものを選ぶ（`days=4`） |
| `test_select_boundary_is_inclusive` | ちょうど 4 日のものを選ぶ |
| `test_select_filters_pattern` | `-beta` のタグを `^\d+\.\d+\.\d+$` で外す |
| `test_select_none_raises` | 候補がないとき `AnsibleLookupError` |
| `test_oci_returns_tag_at_digest` | `skopeo list-tags` と `skopeo inspect --override-os linux --override-arch arm64` の結果から `ref` が `<repo>:<tag>@sha256:...` |
| `test_release_skips_draft_and_prerelease` | draft と prerelease を除外する |
| `test_release_asset_checksum` | asset の `digest` を `checksum` に入れ、`{version}` を展開した名前で asset を選ぶ |
| `test_release_without_digest_has_empty_checksum` | `digest` がないとき `checksum` が空文字 |
| `test_tag_returns_commit_sha` | タグのコミット日時で判定し、`commit` に SHA を返す |
| `test_commit_returns_newest_aged` | デフォルトブランチのコミットから、公開 `days` 日以上の最新の SHA を返す |
| `test_gh_failure_raises` | `run` が失敗したとき、メッセージに stderr を含む `AnsibleLookupError` |
| `test_lookup_caches_identical_calls` | 同じ引数の 2 回の呼び出しで `run` が 1 回分しか呼ばれない |

Run: `uv run --with pytest --with ansible-core pytest tests/test_aged_release.py -q`
Expected: import エラーで FAIL

- [ ] **Step 3: 実装する**

`gh` の呼び出しは `gh api` を使う: Release は `repos/<o>/<r>/releases?per_page=100`、タグは `repos/<o>/<r>/tags?per_page=100` と各タグの `repos/<o>/<r>/commits/<sha>`、コミットは `repos/<o>/<r>/commits?sha=<default>&until=<now - days>&per_page=1`（デフォルトブランチは `repos/<o>/<r>` の `default_branch`）。イメージは `skopeo list-tags docker://<repo>` と、候補を新しい順に `skopeo inspect --override-os linux --override-arch <arch> docker://<repo>:<tag>` で `Created` と `Digest` を読む（今の `resolve_image.py` と同じく、条件を満たした時点で止める）。`gh` と skopeo のパスは PATH から探す。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_aged_release.py -q`
Expected: 13 passed

- [ ] **Step 5: 実物に対して 1 回ずつ呼ぶ**

Run: `ansible localhost -m debug -a "msg={{ lookup('aged_release', 'github-tag:make-all/tuya-local', days=4) }}" -e supply_chain_cooldown_days=4`（ほかに `oci:ghcr.io/gtsteffaniak/filebrowser` と `github-release:kalkih/mini-graph-card` も同様に）
Expected: それぞれ値が返り、`ref` に `@sha256:` が含まれる

- [ ] **Step 6: skopeo を Mac のパッケージに足してコミット**

`roles/darwin/vars/main.yml` の Homebrew のパッケージ一覧に `skopeo` をアルファベット順で足す。

```bash
git add ansible.cfg plugins tests/test_aged_release.py roles/darwin/vars/main.yml
git commit -m "feat: resolve aged releases with a lookup plugin"
```

### Task 2: chezmoi の npm と uv の設定

**Files:**
- Modify（chezmoi リポジトリ `/Volumes/ExternalHD/git/chezmoi`）: `dot_config/npm/npmrc`、`dot_config/uv/uv.toml`
- Modify: `roles/ubuntu/tasks/main.yml`（`npm install -g` の 2 タスク）、`roles/darwin/tasks/main.yml`（2 タスク）、`roles/raspberrypi/tasks/main.yml`（`community.general.npm` の 1 タスク）

- [ ] **Step 1: ユーザーの確認を取って chezmoi を直す**

npmrc に `min-release-age=4` を、uv.toml に `[exclude-newer-package]` の `enecoq-data-fetcher = false` を足す案を示し、了承を得てから編集、コミット、push する（chezmoi リポジトリの規約に従う）。

- [ ] **Step 2: npm のタスクに環境変数を渡す**

5 タスクに `environment: NPM_CONFIG_USERCONFIG: "{{ ansible_env.HOME }}/.config/npm/npmrc"` を足す。

- [ ] **Step 3: 読まれることを確かめる**

Run: `ssh -p 11022 ubuntu@fox.rewse.jp 'sudo -H env NPM_CONFIG_USERCONFIG=/root/.config/npm/npmrc npm config get min-release-age'` と、Mac で `NPM_CONFIG_USERCONFIG=$HOME/.config/npm/npmrc npm config get min-release-age`
Expected: どちらも `4`。root で `null` の場合は、fox の root の chezmoi が apply されているかを確かめて ledger に記録する

- [ ] **Step 4: コミット**

```bash
git add roles/ubuntu/tasks/main.yml roles/darwin/tasks/main.yml roles/raspberrypi/tasks/main.yml
git commit -m "fix: apply the npm release-age cooldown to Ansible runs"
```

### Task 3: docker ロールと filebrowser の compose 切り替え

**Files:**
- Modify: `roles/docker/tasks/main.yml`（`/etc/compose` ディレクトリを作るタスクを追加。`Create compose.yml` と `Add services section` はここでは残す）
- Modify: `roles/filebrowser/tasks/container.yml`、`roles/filebrowser/handlers/main.yml`
- Rename: `roles/filebrowser/templates/compose.yml.j2` → `compose.yaml.j2`

**Interfaces:**
- Produces: 切り替えのタスクの形（Task 4 が各ロールで同じ形を使う）

- [ ] **Step 1: container.yml を書き換える**

順に次のタスクにする。

1. `container | Resolve aged image`: `set_fact` で `__filebrowser_image`（`oci:ghcr.io/gtsteffaniak/filebrowser`、`pattern='^\d+\.\d+\.\d+-stable$'`）
2. `container | Create compose directory`: `/etc/compose/filebrowser`、`mode: "0755"`
3. `container | Deploy compose file`: `compose.yaml.j2` → `/etc/compose/filebrowser/compose.yaml`
4. `container | Read legacy container`: `community.docker.docker_container_info` で `filebrowser` を読み、`__filebrowser_legacy` に register
5. `container | Remove legacy container`: `__filebrowser_legacy.exists` かつラベル `com.docker.compose.project` が `etc` のとき `state: absent`。起動より前に置く理由をコメントに書く
6. `container | Remove legacy compose block`: `/etc/compose.yml` の `filebrowser` の marker のブロックを `state: absent`
7. `container | Start container`: `project_src: /etc/compose/filebrowser`、`state: present`、`pull: missing`

`include_role` の quarantine、`apply.tags`、`# noqa`、`default('')` のガードを消す。

- [ ] **Step 2: テンプレートと handler**

テンプレートを `compose.yaml.j2` に改名し、先頭に `{{ ansible_managed | comment }}` と `name: filebrowser`、`services:` の下に既存の中身を置き、`image: {{ __filebrowser_image.ref }}` にする。handler `Restart filebrowser` は `project_src: /etc/compose/filebrowser`、`state: restarted` にし、`pull` と `recreate` を消す。

- [ ] **Step 3: lint と check**

Run: `ansible-lint --nocolor roles/filebrowser roles/docker; echo "exit=$?"`
Expected: `exit=0`
Run: `direnv exec . ansible-playbook home-primary.yml --tags docker,filebrowser --check --diff`
Expected: 終了コード 0。compose ファイルの新規作成、レガシーのコンテナの削除とブロックの削除、起動が changed になる

- [ ] **Step 4: ユーザーの確認を取って反映し、2 回目を流す**

Run: 同じコマンドを `--check` なしで 2 回
Expected: 1 回目は終了コード 0、2 回目は `changed=0`（docker の `Create compose.yml` の touch を除く。ledger に記録）。`docker inspect filebrowser` のラベル `com.docker.compose.project` が `filebrowser`、`curl https://nas.rewse.jp/` が 200

- [ ] **Step 5: コミット**

```bash
git add roles/docker/tasks/main.yml roles/filebrowser
git commit -m "refactor(filebrowser): run in its own compose project"
```

### Task 4: 残りのロールの compose 切り替え

**Files:** 各ロールの container 関連のタスク、`templates/compose.yaml.j2`（新規。今の `blockinfile` の中身を移す）、handlers、vars（`teslamate_*_image_ref` を削除）

| 順 | ロール | ホスト | lookup | 確認 |
|---|---|---|---|---|
| 1 | litellm | fox | `oci:ghcr.io/berriai/litellm`、`^v\d+\.\d+\.\d+$` | コンテナ healthy、API のポートが応答 |
| 2 | couchdb | fox | `oci:apache/couchdb`、`^\d+\.\d+\.\d+$` | `/_up` が 200 |
| 3 | teslamate | fox | `oci:ghcr.io/rewse/teslamate`、`^main$`、`days=0`。grafana も同様 | Web が 200 |
| 4 | nvr | fox | `oci:ghcr.io/blakeblackshear/frigate`、`^\d+\.\d+\.\d+$` | Frigate の UI が 200、カメラの録画が進む |
| 5 | matter_server | fox | `oci:ghcr.io/home-assistant-libs/python-matter-server`、`^\d+\.\d+\.\d+$` | コンテナが起動（5 と 6 は続けて行う） |
| 6 | homeassistant | fox | `oci:ghcr.io/home-assistant/home-assistant`、`^\d{4}\.\d+\.\d+$` | `mcporter` で Matter のエンティティが available |
| 7 | homeassistant-ha/secondary | hotel | 同上 | 同上（hotel） |

- [ ] **Step 1〜N: 各ロールで Task 3 の Step 1〜5 を繰り返す**

各ロールで、切り替えのタスクの形は Task 3 の Interfaces どおり。teslamate は既存の pre-pull と `pull: never` を残し、pre-pull が `__teslamate_image.ref` を使うようにする。コミットはロールごとに `refactor(<role>): run in its own compose project`。

### Task 5: 共有の compose と docker_quarantine の削除

**Files:**
- Modify: `roles/docker/tasks/main.yml`（`Create compose.yml` と `Add services section` を消し、`/etc/compose.yml` を `state: absent` にするタスクを足す）
- Delete: `roles/docker/quarantine/`
- Modify: `.ansible-lint-ignore`（`roles/docker/quarantine` の行を消す）

- [ ] **Step 1: 残りがないことを確かめる**

Run: `rg -n 'docker/quarantine|docker_quarantine|/etc/compose\.yml' roles`
Expected: docker ロールの削除タスクだけ

- [ ] **Step 2: fox と hotel で反映し、2 回目を流す**

Run: `home-primary.yml` と `home-secondary.yml` を `--tags docker` で check、確認、反映、2 回目
Expected: 2 回目が `changed=0`。`/etc/compose.yml` がない

- [ ] **Step 3: コミット**

```bash
git add -A roles/docker .ansible-lint-ignore
git commit -m "refactor(docker): remove the shared compose file and image quarantine"
```

### Task 6: HA の git コンポーネントとカード

**Files:**
- Modify: `roles/homeassistant/tasks/main.yml`（frigate、frosted-glass-manager、hems_echonet_lite、tuya-local、frosted-glass-themes、card-mod、mini-graph-card、mini-media-player、simple-thermostat、simple-weather-card）
- Modify: `roles/homeassistant/vars/main.yml`（対応する `_version` を削除）

- [ ] **Step 1: git のコンポーネントを置き換える**

各コンポーネントで、`<component> : Resolve aged tag`（`github-tag:`。hems_echonet_lite も `github-tag:` にする）を先頭に足し、`git` の `dest` を `/usr/local/src/<repo name>`、`version` を `__homeassistant_<component>.commit` にする。コピーのタスクに `when: not ansible_check_mode or <checkout>.stat.exists` 相当の条件と、skip の理由を出す `debug`（check mode でチェックアウトがないときだけ。理由を必ず表示するため `verbosity: 0`）を足す。最後に `/tmp/<repo name>` を `state: absent` にするタスクを足す。

- [ ] **Step 2: カードを置き換える**

各カードで `<card> : Resolve aged release`（`github-release:`、`asset` は今の URL のファイル名）を足し、`get_url` の `url` と `checksum` を lookup の値にする。`checksum` は空のとき付けない（`checksum: "{{ x.checksum | default(omit, true) }}"`）。

- [ ] **Step 3: check mode が最後まで流れることを確かめる**

Run: `direnv exec . ansible-playbook home-primary.yml --tags homeassistant --check --diff; echo "exit=$?"`
Expected: `exit=0`（`custom`、`theme`、`lovelace` を除外しない）

- [ ] **Step 4: 確認を取って反映し、2 回目を流す**

Expected: 2 回目が `changed=0`。`mcporter` で tuya_local、frigate、hems_echonet_lite の統合がロードされている

- [ ] **Step 5: コミット**

```bash
git add roles/homeassistant
git commit -m "refactor(homeassistant): resolve components and cards with aged releases"
```

### Task 7: ほかの git と Release

**Files:** 下表のロールの tasks と vars

| ロール | 対象 | lookup |
|---|---|---|
| ubuntu | lightpanda | `github-release:lightpanda-io/browser` |
| raspberrypi | restic、php-miio | `github-release:restic/restic`（`asset='restic_{version}_linux_arm64.bz2'`）、`github-tag:skysilver-lab/php-miio`（`pattern='^v\.\d+(\.\d+)*$'`） |
| darwin | Source Han Mono / Sans / Serif | `github-release:adobe-fonts/source-han-*`（`pattern` は各リポジトリのタグ形式に合わせる） |
| power_monitor | pkg | `github-release:SAP/power-monitoring-tool-for-macos` |
| zabbix/mcp | ソース | `github-tag:initMAX/zabbix-mcp-server` |
| zabbix/server | ssl-cert-check | `github-commit:Matty9191/ssl-cert-check`、`/usr/local/src/ssl-cert-check`、旧 `/srv/git/ssl-cert-check` を削除 |
| desktop | one-gnome-terminal | `github-commit:denysdovhan/one-gnome-terminal`、同上 |
| database/client | Redshift JDBC | `github-release:aws/amazon-redshift-jdbc-driver` |

- [ ] **Step 1: 各ロールを置き換え、vars の `_version` を消す**

power_monitor の `tests/version.yml` は URL を lookup の値で組む形に合わせて直す。

- [ ] **Step 2: ホストごとに check、確認、反映、2 回目**

fox と hotel は `--tags ubuntu,raspberrypi,zabbix_mcp,zabbix_server`、alfa は `--tags ubuntu,desktop,database_client`、Mac は `darwin-personal.yml --tags darwin,power_monitor`。
Expected: 2 回目が `changed=0`

- [ ] **Step 3: コミット（ロールごと）**

`refactor(<role>): resolve <component> with aged releases`

### Task 8: GitHub 以外の配布元とインストーラ

**Files:**
- Modify: `roles/database/client/tasks/main.yml`、`vars/main.yml`（Oracle、MySQL）
- Modify: `roles/database/client/gui/tasks/main.yml`、`vars/main.yml`（SCT、Corretto のコメント）
- Create: `roles/httpd/vars/ubuntu.yml`、`roles/httpd/tasks/set_vars.yml`、Modify: `roles/httpd/tasks/main.yml`（先頭で `set_vars.yml` を import、`always` タグ）、`roles/httpd/vars/main.yml`
- Modify: `roles/raspberrypi/vars/main.yml`（netgear を削除）
- Modify: `roles/ubuntu/tasks/main.yml`、`roles/raspberrypi/tasks/main.yml`、`roles/darwin/personal/tasks/main.yml`、`roles/couchdb/tasks/main.yml`（インストーラの自己更新）

- [ ] **Step 1: 配布元を最新版にする**

spec の表どおり。Oracle は `instantclient-{basic,sqlplus,...}-linux{-arm64|x64}.zip` を `unarchive` し、`ansible.builtin.find` で `/srv/instantclient_*` を求めて以後の参照に使う。MySQL の apt 設定は固定 URL の deb にし、既存の版比較のタスクを消す。Connector/J は `apt-cache policy mysql-connector-j` で存在を確かめ、あれば `apt` で入れる。ない場合は ledger に `Ruling:` を残し、配布元の最新版の URL を探す。

- [ ] **Step 2: インストーラの自己更新を足す**

各ツールに `<tool> : Update` のタスクを足し、`update` タグを付ける。コマンド: `uv self update`、`claude update`、`deno upgrade`、kiro-cli・nix・zinit は各ツールの公式の更新コマンドを確かめて使う。`changed_when` は出力で判定する。

- [ ] **Step 3: check、確認、反映、2 回目**

Expected: 2 回目が `changed=0`

- [ ] **Step 4: コミット**

`refactor: track the latest release of non-GitHub tools`

### Task 9: ドキュメント

**Files:** `AGENTS.md`（Update Policy、置き場所、Quoting の `compose.yaml` の例外）、`README.md`（プロジェクト構成に `plugins/`、`tests/`）

- [ ] **Step 1: spec の「ドキュメント」の節を反映する**

- [ ] **Step 2: 確かめてコミット**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files; echo "exit=$?"`
Expected: `exit=0`

```bash
git add AGENTS.md README.md
git commit -m "docs: describe aged release resolution and file locations"
```

### Task 10: 全体の確認と反映

- [ ] **Step 1: 完了条件の残りを確かめる**

Run: `rg -n '_version:' roles/*/vars roles/*/*/vars roles/*/*/*/vars`
Expected: `database_corretto_version` と `httpd_php_version` だけ（それぞれ理由のコメント付き）
Run: `rg -n '/srv/git/(ssl-cert-check|one-gnome-terminal)|dest: /tmp/' roles`
Expected: 出力なし

- [ ] **Step 2: 4 台で 2 回ずつ流す**

`home-primary.yml`、`home-secondary.yml`、`cloud-workstation.yml`、`darwin-personal.yml`。確認を取ってから流す。
Expected: 2 回目がすべて `changed=0`、終了コード 0。fox の `--check` がタスクを除外せずに終了コード 0

- [ ] **Step 3: main に反映して CI を確かめる**

Run: `git switch main && git merge --ff-only refactor/update-policy && git push origin main && git branch -d refactor/update-policy`
Expected: `Ansible Lint`、`Gitleaks` が `success`
