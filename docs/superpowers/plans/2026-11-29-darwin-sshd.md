# 個人用 Mac の鍵認証だけの SSH 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 個人用 Mac の sshd でパスワード認証とキーボード対話式認証を拒否し、iPhone と iPad の Rex の鍵を `~/.ssh/authorized_keys` に足す。

**Architecture:** darwin ロールに `sshd` コンポーネントを足す。設定ファイル `000-key-only.conf` は、`path.yml` と同じようにチェックサムが違うときだけ become して置く。鍵は `ansible.posix.authorized_key` で 1 本ずつ足す。どのタスクも、`darwin_sshd_authorized_keys` が定義されたホスト（`darwin_personal`）だけで動く。

**Tech Stack:** Ansible（`stat`、`copy`、`ansible.posix.authorized_key`）、pytest + unittest、PyYAML。

**Spec:** `docs/superpowers/specs/2026-11-29-darwin-sshd-design.md`

## Global Constraints

- 作業は worktree `.worktrees/darwin-sshd`（ブランチ `feat/darwin-sshd`）で行う。
- 設定ファイルの置き場所は `/etc/ssh/sshd_config.d/000-key-only.conf`。設定行は `PasswordAuthentication no` と `KbdInteractiveAuthentication no` の 2 行だけにする。
- 鍵は `inventory/host_vars/fox.rewse.jp/ubuntu.yml` にある `rex@atom` と `rex@chemical` の 2 行をそのまま使う。
- `darwin_sshd_authorized_keys` が未定義のホストでは、コンポーネントの全タスクを skip する。
- 変更がない実行では become しない。`darwin-personal.yml` は `connection: local` で動き、become のパスワードは `-K` で渡す。エージェントは `-K` のプロンプトに答えられないので、become が必要な実行（設定ファイルが違うときの check mode と適用）はユーザーに頼む。
- タスク名は `sshd | <命令形>`、変数は `darwin_sshd_`、register は `__darwin_sshd_` で始める。`mode` は `"0644"` の形で書く。

## Review Focus

- `000-key-only.conf` が `100-macos.conf` より後に並ぶと、macOS 側の値に負ける。今の `100-macos.conf` に該当する項目はないが、名前で先に読ませておく（Task 1 のテスト `test_config_is_read_before_macos_defaults`）。
- 壊れた設定を置くと、次の SSH 接続から sshd が起動しなくなる。置く前に `sshd -t` で検証する（Task 1 のテスト `test_config_is_validated_before_it_is_placed`）。
- 鍵を足すときに、既存の RSA の鍵を消さない（Task 1 のテスト `test_keys_are_added_without_removing_others`）。
- 会社の Mac では何もしない（Task 1 のテスト `test_every_task_skips_without_keys` と `test_only_the_personal_mac_lists_keys`）。
- 2 回目の実行で become を求めない（Task 1 のテスト `test_copy_runs_only_when_the_file_differs`）。

---

### Task 1: darwin ロールの sshd コンポーネント

**Files:**
- Create: `roles/darwin/files/000-key-only.conf`、`roles/darwin/tasks/sshd.yml`
- Modify: `roles/darwin/tasks/main.yml`（`security.yml` の import の次）、`roles/darwin/vars/main.yml`、`roles/darwin/defaults/main.yml`、`inventory/group_vars/darwin_personal/darwin.yml`
- Test: `tests/test_darwin_sshd.py`

**Interfaces:**
- Produces: インベントリ変数 `darwin_sshd_authorized_keys`（公開鍵 1 行ずつのリスト）、定数 `darwin_sshd_config_path`（`/etc/ssh/sshd_config.d/000-key-only.conf`）、タグ `darwin_sshd`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_darwin_sshd.py` に、ヘルパー `tasks() -> list[dict]`（`roles/darwin/tasks/sshd.yml` を読む）と `task(name: str) -> dict` を書く。`when_text(t: dict) -> str` は、`when` が文字列ならそのまま返し、リストなら `" and "` でつないで返す。

```python
ROLE = REPO_ROOT / "roles" / "darwin"
CONFIG = ROLE / "files" / "000-key-only.conf"

def test_config_rejects_passwords_and_keyboard_interactive(self):
    lines = [l for l in CONFIG.read_text().splitlines() if l and not l.startswith("#")]
    self.assertEqual(lines, ["PasswordAuthentication no", "KbdInteractiveAuthentication no"])

def test_config_is_read_before_macos_defaults(self):
    path = yaml.safe_load((ROLE / "vars" / "main.yml").read_text())["darwin_sshd_config_path"]
    self.assertEqual(path, "/etc/ssh/sshd_config.d/000-key-only.conf")
    self.assertLess(pathlib.PurePath(path).name, "100-macos.conf")

def test_copy_runs_only_when_the_file_differs(self):
    check = task("sshd | Check key-only configuration")
    self.assertEqual(check["ansible.builtin.stat"]["path"], "{{ darwin_sshd_config_path }}")
    self.assertEqual(check["ansible.builtin.stat"]["checksum_algorithm"], "sha1")
    self.assertEqual(check["register"], "__darwin_sshd_config")
    copy = task("sshd | Copy key-only configuration")
    self.assertTrue(copy["become"])
    self.assertIn("__darwin_sshd_config.stat.checksum", when_text(copy))
    self.assertIn("lookup('ansible.builtin.file', '000-key-only.conf', rstrip=false)", when_text(copy))

def test_config_is_validated_before_it_is_placed(self):
    copy = task("sshd | Copy key-only configuration")["ansible.builtin.copy"]
    self.assertEqual(copy["validate"], "/usr/sbin/sshd -t -f %s")
    self.assertEqual((copy["src"], copy["dest"], copy["mode"]), ("000-key-only.conf", "{{ darwin_sshd_config_path }}", "0644"))
    self.assertEqual((copy["owner"], copy["group"]), ("root", "wheel"))

def test_keys_are_added_without_removing_others(self):
    keys = task("sshd | Authorize keys")
    module = keys["ansible.posix.authorized_key"]
    self.assertEqual(module["user"], "{{ ansible_facts['user_id'] }}")
    self.assertEqual(module["key"], "{{ item }}")
    self.assertNotIn("exclusive", module)
    self.assertEqual(keys["loop"], "{{ darwin_sshd_authorized_keys | default([]) }}")
    self.assertNotIn("become", keys)

def test_every_task_skips_without_keys(self):
    for t in tasks():
        self.assertIn("darwin_sshd_authorized_keys is defined", when_text(t))

def test_component_is_imported_with_its_tag(self):
    imports = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    names = [t["ansible.builtin.import_tasks"] for t in imports]
    self.assertEqual(names[names.index("security.yml") + 1], "sshd.yml")
    self.assertEqual(imports[names.index("sshd.yml")]["tags"], ["darwin_sshd"])

def test_only_the_personal_mac_lists_keys(self):
    personal = REPO_ROOT / "inventory" / "group_vars" / "darwin_personal" / "darwin.yml"
    comments = [k.split()[-1] for k in yaml.safe_load(personal.read_text())["darwin_sshd_authorized_keys"]]
    self.assertEqual(comments, ["rex@atom", "rex@chemical"])
    for path in (REPO_ROOT / "inventory").rglob("*.yml"):
        if path != personal:
            self.assertNotIn("darwin_sshd_authorized_keys", path.read_text())
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_darwin_sshd.py -v`
Expected: FAIL（8 件）。`FileNotFoundError`（`000-key-only.conf` と `sshd.yml` がまだない）、`KeyError: 'darwin_sshd_config_path'`、`StopIteration`。

- [ ] **Step 3: 実装する**

`files/000-key-only.conf` には、まず英語のコメントを書く。書くことは、Ansible が管理しているファイルであること、`UsePAM yes` のもとでは `KbdInteractiveAuthentication no` がないとパスワードを聞く道が残ること、sshd は最初に読んだ値を使うので `100-macos.conf` より前に並ぶ名前にしていること。コメントの後に設定の 2 行を置く。

`vars/main.yml` には `darwin_sshd_config_path` を置く。`defaults/main.yml` には、`# darwin_sshd_authorized_keys:` と例の 1 行をコメントにして置く。

`sshd.yml` には次の 3 つのタスクをこの順で置き、どれも `when` に `darwin_sshd_authorized_keys is defined` を含める。

- `sshd | Check key-only configuration`
- `sshd | Copy key-only configuration`: `when` は `path.yml` と同じチェックサム比較にする。コメントには 2 つのことを書く。比較しておくと、変更がない実行で become のパスワードを求めないこと。壊れた設定を置くと次の接続から sshd が起動しないので、検証してから置くこと。
- `sshd | Authorize keys`

`main.yml` では、`security.yml` の import の次に `sshd.yml` をタグ `darwin_sshd` で import する。`inventory/group_vars/darwin_personal/darwin.yml` の `darwin_sshd_authorized_keys` に 2 本の鍵を置き、それぞれどの端末の Rex の鍵かをコメントで添える。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_darwin_sshd.py -v`
Expected: PASS（8 件）

- [ ] **Step 5: lint と全テストを通す**

Run: `git add roles/darwin inventory/group_vars/darwin_personal/darwin.yml tests/test_darwin_sshd.py && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure && uv run --with pytest --with ansible-core pytest tests`
Expected: すべての hook が Passed になり、pytest もすべて PASS。

- [ ] **Step 6: コミットする**

```bash
git add roles/darwin inventory/group_vars/darwin_personal/darwin.yml tests/test_darwin_sshd.py
git commit -m "feat(darwin): accept only SSH keys on the personal Mac and add the Rex keys"
```

### Task 2: Mac への適用と確認

**Files:** なし

- [ ] **Step 1: ユーザーに check mode で差分を見てもらう**

設定ファイルがまだないので、check mode でも become が必要になる。ユーザーに、worktree で次のコマンドを実行してもらう: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook darwin-personal.yml --tags darwin_sshd --check --diff -K`
Expected: 終了コード 0。`Copy key-only configuration` は設定の 2 行が増える差分で changed になる。`Authorize keys` は 2 本とも changed になり、既存の RSA の鍵の行は差分に出ない。

- [ ] **Step 2: ユーザーに適用してもらう**

Run: Step 1 のコマンドから `--check --diff` を外し、ユーザーに実行してもらう。
Expected: 終了コード 0、failed=0。

- [ ] **Step 3: 2 回目が changed=0 で、become を求めないことを確かめる**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook darwin-personal.yml --tags darwin_sshd`（`-K` は付けない。エージェントが実行する）
Expected: 終了コード 0、`changed=0`。パスワードを聞かれない。

- [ ] **Step 4: パスワードが拒否されることを確かめる**

ユーザーにリモートログインをオンにしてもらう。そのあと、`ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive -o BatchMode=yes tats@localhost true` を実行する。
Expected: `Permission denied (publickey).` で失敗し、パスワードの方式は一覧に出ない。

- [ ] **Step 5: iPhone から繋がることを確かめる**

ユーザーに、家の Wi-Fi か Teleport の VPN から、iPhone の Rex で `ssh://tats@youth.local` を追加してもらう。`.local` で名前が引けないときは、Mac の LAN の IP アドレスで試してもらう。
Expected: Mac の Rex のセッションが iPhone で開ける。

### Task 3: マージ

- [ ] **Step 1: push と PR の作成をユーザーに確認する**

- [ ] **Step 2: PR を squash でマージする**

PR のタイトルは `feat(darwin): accept only SSH keys on the personal Mac` にする。マージの前に、spec と plan を `docs/superpowers/archive/` に移す。
