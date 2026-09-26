# Ansible 規約の刷新 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新しい Ansible 規約を AGENTS.md に定め、ansible-lint を pre-commit と CI で強制し、`filebrowser` を見本として規約に移行する。

**Architecture:** 既存の違反は `.ansible-lint-ignore` に記録して CI を最初から通し、新しいコードだけに規約を強制する。`filebrowser` は `tasks/main.yml` から 4 つの component ファイルを `import_tasks` する形に分け、ignore なしで lint を通し、fox で 2 回目の実行が `changed=0` になることで移行を確かめる。

**Tech Stack:** ansible-core 2.21.3、ansible-lint 26.8.0、pre-commit（`uvx` 経由）、GitHub Actions、Dependabot

**Spec:** `docs/superpowers/specs/2026-09-26-ansible-conventions-design.md`

## Global Constraints

- 作業は `main` から切ったブランチ `refactor/ansible-conventions` で行う。`main` へ直接 push しない
- ansible-lint の `profile: production`、`enable_list: [name[prefix]]`、`skip_list` は空、`exclude_paths: [roles/homeassistant/files/]`
- pre-commit の ansible-lint フックは `rev: v26.8.0`
- Action は SHA 固定: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`、`astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0`
- Dependabot の `cooldown.default-days: 4`
- 稼働中のホスト（fox）への `--check` なしの実行は、実行前にユーザーの確認を取る
- プレイブックの成否はプロセスの終了コードで判断する
- コードコメントとコミットメッセージは英語、Conventional Commits に従う

## Review Focus

- `--tags update` だけで流したとき、解決したイメージが compose に反映されて起動まで進むこと。`container.yml` の `import_tasks` に `update` があることを Task 5 の `--list-tasks` で確かめる
- `--tags filebrowser_apache` のように component タグ単独で流したとき、必要な handler だけが動き、ほかの component のタスクが走らないこと。Task 5 の `--list-tasks` で確かめる
- イメージが解決できなかったとき（`docker_quarantine_image_ref` が空）に compose が書き換わらず、コンテナが止まらないこと。既存の `when` を残し、Task 5 の check で `SKIPPED` 表示か正常な解決のどちらかになることを確かめる
- check mode でマウント確認とイメージ解決が失敗しないこと。`check_mode: false` と `changed_when: false` を残し、Task 5 の `--check` が終了コード 0 になることで確かめる
- handler 名を変えても他ロールの同名 handler（`nvr`、`httpd` の `apache: Reload`、`ubuntu` の `fail2ban: Restart`）と衝突しないこと。新しい名前が playbook 内で一意であることを Task 5 の lint（`name[unique]`）で確かめる

---

### Task 1: ansible-lint の設定と ignore の基準線

**Files:**
- Modify: `.ansible-lint`
- Create: `.ansible-lint-ignore`

**Interfaces:**
- Produces: `.ansible-lint-ignore`（`<path> <rule>` 形式）。Task 5 で `roles/filebrowser` の行を消す

- [ ] **Step 1: ブランチを作る**

Run: `git switch -c refactor/ansible-conventions`

- [ ] **Step 2: `.ansible-lint` を spec の内容に書き換える**

`profile: production`、`enable_list` に `name[prefix]`、`skip_list` を削除、`exclude_paths` は `roles/homeassistant/files/` のまま。

- [ ] **Step 3: 新しい設定で違反が出ることを確かめる**

Run: `ansible-lint --nocolor 2>&1 | tail -5`
Expected: 終了コード非 0、`name[prefix]`、`name[casing]`、`name[play]`、`role-name[path]` を含む違反が出る

- [ ] **Step 4: ignore を生成する**

Run: `ansible-lint --generate-ignore --nocolor >/dev/null 2>&1; wc -l .ansible-lint-ignore`
Expected: `.ansible-lint-ignore` ができ、`roles/filebrowser` の行を含む

- [ ] **Step 5: ignore 込みで通ることを確かめる**

Run: `ansible-lint --nocolor; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 6: コミット**

```bash
git add .ansible-lint .ansible-lint-ignore
git commit -m "build: enforce ansible-lint production profile with baseline ignore"
```

### Task 2: pre-commit

**Files:**
- Create: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: Task 1 の `.ansible-lint` と `.ansible-lint-ignore`
- Produces: フック ID `ansible-lint`。Task 3 の CI が `uvx pre-commit run --all-files` で同じものを動かす

- [ ] **Step 1: `.pre-commit-config.yaml` を作る**

`repo: https://github.com/ansible/ansible-lint`、`rev: v26.8.0`、`hooks: [{id: ansible-lint}]` の 1 エントリだけ。

- [ ] **Step 2: 手元で通ることを確かめる**

Run: `uvx pre-commit run --all-files; echo "exit=$?"`
Expected: `ansible-lint....Passed`、`exit=0`。`requirements.yml` の collection 取得で失敗する場合は、フックの `additional_dependencies` ではなく `requirements.yml` の内容を確認する

- [ ] **Step 3: 新しい違反で落ちることを確かめる**

ignore はファイルとルールの組で記録されるため、既存ファイルでは試さない。ignore に載っていない一時ファイル `roles/filebrowser/tasks/tmp.yml` に小文字始まりの名前のタスク（`ansible.builtin.debug`）を 1 つ書き、`uvx pre-commit run --all-files` が `name[casing]` で失敗することを確かめたら削除する。

- [ ] **Step 4: コミット**

```bash
git add .pre-commit-config.yaml
git commit -m "build: run ansible-lint via pre-commit"
```

### Task 3: GitHub Actions と Dependabot

**Files:**
- Create: `.github/workflows/ansible-lint.yml`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: Task 2 の `.pre-commit-config.yaml`

- [ ] **Step 1: ワークフローを作る**

`name: Ansible Lint`、`on: [push, pull_request]`、`permissions: contents: read`、job `lint`（`runs-on: ubuntu-latest`）の steps は Global Constraints の SHA で `actions/checkout`、`astral-sh/setup-uv`、続けて `run: uvx pre-commit run --all-files --show-diff-on-failure`。既存の `gitleaks.yml` と同じ書式（2 スペース、job に `name:`）に合わせる。

- [ ] **Step 2: Dependabot の設定を作る**

`version: 2`、`updates` に `package-ecosystem: pre-commit` と `package-ecosystem: github-actions` の 2 つ。どちらも `directory: /`、`schedule.interval: weekly`、`cooldown.default-days: 4`。

- [ ] **Step 3: 構文を確かめる**

Run: `ansible-lint --nocolor .github/ ; uvx --from actionlint-py actionlint .github/workflows/ansible-lint.yml; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 4: コミット**

```bash
git add .github/workflows/ansible-lint.yml .github/dependabot.yml
git commit -m "ci: lint Ansible content and update pinned tools with Dependabot"
```

CI の実行確認は Task 6 で行う。

### Task 4: AGENTS.md と README.md

**Files:**
- Modify: `AGENTS.md`（「## Ansible Conventions」節全体）
- Modify: `README.md:105-160`（タグの例、1Password の記述、Best Practices）

- [ ] **Step 1: AGENTS.md の「Ansible Conventions」を書き直す**

spec の「規約」節の内容を英語のルールとして書く。小見出しは Update Policy、Role Design、Platform Differences、Role Names、Task Names、Tags、Ordering、Variables、Quality、Lint の順。「Repository Operations」以降は変えない。次を必ず含める。

- `group_vars/all` の共有値の一覧: `admin`、`email`、`global_ip`、`ipv6`（今後 `supply_chain_cooldown_days` を追加予定と書く）
- 規約の手本として `roles/filebrowser` を参照する一文
- 移行済みロールは `.ansible-lint-ignore` から行を消すという運用
- Common Standards の Rule Authoring に従い、各ルールは指示から書き、理由はルールの範囲を明確にするときだけ添える

- [ ] **Step 2: README.md を直す**

`--tags ubuntu,package` と `--tags package` の例を、ロール名タグ（`--tags ubuntu`）、component タグ（`--tags ubuntu_fail2ban`）、`--tags update` の例に置き換える。`lookup('pipe', 'op read ...')` の記述は、Secret Reference を 1Password の `ansible` vault の item ID で参照する旨に合わせる。「Project Structure」の図はサブプロジェクト 2 で直すので触らない。

- [ ] **Step 3: 人間向け文書としての確認**

`~/.agents/skills/humanizer/SKILL.md` の §1〜§5 に当たる表現がないかを AGENTS.md の書き換え部分で確認し、あれば直す。
Run: `uvx pre-commit run --all-files; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 4: コミット**

```bash
git add AGENTS.md README.md
git commit -m "docs: rewrite Ansible conventions"
```

### Task 5: `filebrowser` の移行

**Files:**
- Modify: `roles/filebrowser/tasks/main.yml`
- Create: `roles/filebrowser/tasks/config.yml`、`container.yml`、`apache.yml`、`fail2ban.yml`
- Modify: `roles/filebrowser/handlers/main.yml`
- Modify: `roles/filebrowser/templates/config.yaml.j2`、`fail2ban-filter.conf.j2`、`fail2ban-jail.conf.j2`、`nas.rewse.jp.conf.j2`（先頭行）
- Modify: `singleton_int1.yml`（`filebrowser` の行）
- Modify: `.ansible-lint-ignore`（`roles/filebrowser` の行を削除）

**Interfaces:**
- Consumes: `docker/quarantine` ロール（`quarantine_repo`、`quarantine_tag_pattern` を渡し、`docker_quarantine_image_ref` を受け取る。変更しない）
- Produces: タグ `filebrowser`、`filebrowser_config`、`filebrowser_container`、`filebrowser_apache`、`filebrowser_fail2ban`、`update`。handler `Restart filebrowser`、`Reload Apache`、`Restart fail2ban`

- [ ] **Step 1: ignore から filebrowser の行を消し、lint が落ちることを確かめる**

`.ansible-lint-ignore` から `roles/filebrowser` で始まる行をすべて削除する。
Run: `ansible-lint --nocolor roles/filebrowser; echo "exit=$?"`
Expected: 終了コード非 0

- [ ] **Step 2: component ファイルに分ける**

既存タスクを次のように移す。タスクの中身（モジュール、引数、`when`、`no_log`、`changed_when`、`check_mode`、コメント）は変えず、`tags:` はすべて削除する。

| ファイル | 移すタスク（現在の名前） | 新しい名前 |
|---|---|---|
| `config.yml` | Fail when the published volume is not mounted / Create data directory / Deploy configuration file | `config \| Fail when the published volume is not mounted` / `config \| Create data directory` / `config \| Deploy configuration file` |
| `container.yml` | Resolve quarantined image / Add FileBrowser service to compose / Pull and update container | `container \| Resolve aged image` / `container \| Add service to compose` / `container \| Start container` |
| `apache.yml` | Copy Apache vhost config / Enable Apache site | `apache \| Deploy vhost config` / `apache \| Enable site` |
| `fail2ban.yml` | Copy fail2ban filter / Copy fail2ban jail config | `fail2ban \| Deploy filter` / `fail2ban \| Deploy jail config` |

個別の変更:
- `container | Resolve aged image` の `include_role` の `apply.tags` は削除する（タグは `import_tasks` から継承される）。`name: docker/quarantine` はそのまま
- `config | Deploy configuration file` から `backup: true` を削除する
- `apache | Enable site` は `register: __filebrowser_a2ensite`、`changed_when` もその名前に合わせ、`a2ensite` に対応するモジュールがないため `command` を使う旨の英語コメントを付ける
- `notify` を新しい handler 名に合わせる

- [ ] **Step 3: `tasks/main.yml` を import だけにする**

順に `config.yml`（tags `filebrowser_config`）、`container.yml`（tags `filebrowser_container`、`update`）、`apache.yml`（tags `filebrowser_apache`）、`fail2ban.yml`（tags `filebrowser_fail2ban`）を `ansible.builtin.import_tasks` で読み込む。タスク名は `Import <component> tasks`。

- [ ] **Step 4: handler とテンプレートを直す**

handler 名を `Reload Apache`、`Restart fail2ban`、`Restart filebrowser` にする（中身は変えない、アルファベット順は維持）。4 つのテンプレートの先頭の `# {{ ansible_managed }}` を `{{ ansible_managed | comment }}` に置き換える。`config.yaml.j2` は `---` の次の行を置き換える。`compose.yml.j2` は変えない。

- [ ] **Step 5: playbook にロール名タグを付ける**

`singleton_int1.yml` の `- filebrowser` を `- role: filebrowser` と `tags: [filebrowser]`（インデントした YAML リスト）に変える。ほかのロールの行は変えない。

- [ ] **Step 6: lint が通ることを確かめる**

Run: `ansible-lint --nocolor roles/filebrowser; echo "exit=$?"`
Expected: `exit=0`（ignore に filebrowser の行がない状態で）
Run: `rg -c '^roles/filebrowser' .ansible-lint-ignore`
Expected: 出力なし

- [ ] **Step 7: タグの効き方を確かめる**

Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags filebrowser --list-tasks`
Expected: `filebrowser : config | ...` から `filebrowser : fail2ban | ...` までの全タスクが spec の順で並ぶ
Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags filebrowser_apache --list-tasks`
Expected: `apache | ...` の 2 タスクだけ
Run: `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags update --list-tasks | rg 'filebrowser :'`
Expected: `container | ...` のタスク（quarantine のタスクを含む）が含まれ、`config` や `apache` のタスクは含まれない

- [ ] **Step 8: check mode で差分を確かめる**

Run: `direnv exec . ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags filebrowser --check --diff; echo "exit=$?"`
Expected: `exit=0`。変更はテンプレート 4 ファイルの先頭行だけで、compose ブロックとコンテナには変更がない。1Password の lookup が失敗したときは AGENTS.md の 1Password の節に従う

- [ ] **Step 9: ユーザーの確認を取ってから反映する**

Step 8 の差分と、Apache の reload、fail2ban と filebrowser の再起動が 1 回ずつ起きる見込みをユーザーに示し、了承を得る。
Run: `direnv exec . ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags filebrowser; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 10: 2 回目の実行で変更がないことを確かめる**

Run: `direnv exec . ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags filebrowser; echo "exit=$?"`
Expected: PLAY RECAP で fox が `changed=0`、`exit=0`

- [ ] **Step 11: pre-commit を通してコミット**

Run: `uvx pre-commit run --all-files; echo "exit=$?"`
Expected: `exit=0`

```bash
git add roles/filebrowser singleton_int1.yml .ansible-lint-ignore
git commit -m "refactor(filebrowser): adopt new Ansible conventions"
```

### Task 6: CI の確認

**Files:** なし

- [ ] **Step 1: ユーザーの確認を取ってブランチを push し、PR を作る**

Run: `git push -u origin refactor/ansible-conventions && gh pr create --title "refactor: adopt new Ansible conventions" --body "<spec へのリンク、変更概要、検証結果（Task 5 Step 8〜10 の結果）>" | cat`

- [ ] **Step 2: lint ワークフローの成功を確かめる**

Run: `gh pr checks --watch | cat`
Expected: `Ansible Lint` と `Gitleaks` が `pass`

- [ ] **Step 3: 完了条件を照合する**

spec の「完了条件」5 項目それぞれについて、Task 2 Step 2、この Task の Step 2、Task 5 Step 6、Task 5 Step 10、Task 4 の成果物を根拠として示す。
