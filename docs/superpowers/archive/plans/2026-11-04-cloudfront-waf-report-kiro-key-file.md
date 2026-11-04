# cloudfront-waf-report の Kiro API キーを値だけのファイルにする実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kiro API キーを `~/.config/environment/kiro.sh` の export 行から、値だけを書いた `~/.config/cloudfront-waf-report/kiro-api-key` に移す。

**Architecture:** chezmoi がキーのファイルを fox にだけ 0600 で配り、`kiro.sh` を消す。ansible-playbooks の `cloudfront-waf-report` は `config.json` の `kiro_api_key_file` が指すファイルを読み、前後の空白を除いた中身をキーとして使う。

**Tech Stack:** chezmoi テンプレート、Python 3 標準ライブラリ、unittest、Ansible、systemd

**Spec:** `docs/superpowers/archive/specs/2026-11-04-cloudfront-waf-report-kiro-key-file-design.md`

## Global Constraints

- キーの置き場所: `/home/{{ admin_user }}/.config/cloudfront-waf-report/kiro-api-key`（fox では `/home/tats/...`）、モード 0600、持ち主は `tats`。
- 1Password の Secret Reference: `op://chezmoi/l2kqwiv5em4t4j2kxaat2py5fy/credential`（変えない）。
- `config.json` のキー名: `kiro_api_key_file`。`kiro_env_file` は残さない。
- キーの値をエラー、ログ、メール、テストの出力に出さない。
- 作業場所: ansible-playbooks は worktree `/tmp/ap-waf-kiro-key`（ブランチ `feat/waf-report-kiro-key`）、chezmoi は `~/git/chezmoi` の `main`。
- GitHub への push は、ssh-agent に鍵がない間は `git -c credential.helper='!gh auth git-credential' push https://github.com/rewse/<repo>.git <branch>` を使う。
- 土曜 07:47 JST 前後は切り替え（Task 3）をしない。

## Review Focus

- 末尾に改行があるキーのファイル（chezmoi の出力や手で書いたファイル）: 改行を除いた値を使う。Task 1 の `test_read_api_key_strips_whitespace` で押さえる。
- 空、または空白だけのファイル: `RuntimeError` になり、メッセージにパスが入る。Task 1 の `test_read_api_key_rejects_empty_file` で押さえる。
- キーのファイルがない（切り替えの途中）: `OSError` が既存の except 節で捕まり、「AI 判定なし」のメールになる。Task 1 の `test_missing_key_file_reports_without_ai` で押さえる。
- fox 以外のホスト: `~/.config/cloudfront-waf-report` ができない。Task 2 の `test_report_key_is_fox_only` と `chezmoi managed` の確認で押さえる。
- fox に残った古い `kiro.sh`: `.chezmoiremove` で消える。Task 3 Step 1 の確認で押さえる。

---

### Task 1: スクリプトを値だけのキーのファイルに対応させる（ansible-playbooks）

**Files:**
- Modify: `roles/cloudfront_waf_report/files/cloudfront-waf-report`（91 行目の `_API_KEY`、284〜289 行目の `read_api_key`、772 行目の `config["kiro_env_file"]`）
- Modify: `roles/cloudfront_waf_report/templates/config.json.j2`
- Test: `tests/test_cloudfront_waf_report.py`、`tests/test_cloudfront_waf_report_role.py`
- Commit: spec とこの plan

**Interfaces:**
- Produces: `read_api_key(path: pathlib.Path) -> str`。中身を `strip()` した文字列を返す。空なら `RuntimeError(f"Kiro API key file is empty: {path}")`。
- Produces: `config.json` の `"kiro_api_key_file": "/home/{{ admin_user }}/.config/cloudfront-waf-report/kiro-api-key"`。

- [ ] **Step 1: テストを書き換える**

`tests/test_cloudfront_waf_report.py` の `test_read_api_key_parses_export_line` を次の 2 つに置き換える。

```python
def test_read_api_key_strips_whitespace(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "kiro-api-key"
        path.write_text("abc-123\n")
        self.assertEqual(report.read_api_key(path), "abc-123")

def test_read_api_key_rejects_empty_file(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "kiro-api-key"
        path.write_text(" \n")
        with self.assertRaisesRegex(RuntimeError, re.escape(str(path))):
            report.read_api_key(path)
```

`MainTest.setUp` のキーのファイルを `root / "kiro-api-key"` に `"k\n"` を書く形にし、設定のキーを `"kiro_api_key_file"` にする。`MainTest` に `test_missing_key_file_reports_without_ai` を足す。キーのファイルを消し、候補が 1 件出る answers で `main` を動かして、送られたメールの件名が `": AI 判定なし"` で終わり、戻り値が 0 であることを確かめる。answers と送信の捕まえ方は、`test_main_falls_back_when_kiro_fails` に合わせる。

`tests/test_cloudfront_waf_report_role.py` の `test_config_template_renders_valid_json` の期待値を `"kiro_api_key_file": "/home/tats/.config/cloudfront-waf-report/kiro-api-key"` にする。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_cloudfront_waf_report.py tests/test_cloudfront_waf_report_role.py`
Expected: `test_read_api_key_strips_whitespace`、`test_read_api_key_rejects_empty_file`、`test_config_template_renders_valid_json` と、`kiro_api_key_file` を使う `MainTest` のテストが FAIL

- [ ] **Step 3: 実装する**

`_API_KEY` を消し、`read_api_key` を Interfaces のとおりに書き直す。docstring は「Return the Kiro API key from a file that holds only the key.」にする。772 行目を `config["kiro_api_key_file"]` にする。`config.json.j2` の `kiro_env_file` の行を `kiro_api_key_file` の行に置き換える。`re` はほかでも使っているので import は残す。

- [ ] **Step 4: テストと lint を通す**

Run: `uv run --with pytest --with ansible-core pytest tests` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`（新しいファイルを先に `git add` する）
Expected: どちらも成功

- [ ] **Step 5: コミットする**

```bash
git add docs/superpowers/specs/2026-11-04-cloudfront-waf-report-kiro-key-file-design.md docs/superpowers/plans/2026-11-04-cloudfront-waf-report-kiro-key-file.md roles/cloudfront_waf_report tests/test_cloudfront_waf_report.py tests/test_cloudfront_waf_report_role.py
git commit -m "refactor(cloudfront_waf_report): read the Kiro API key from a key-only file"
```

本文には、export 行を正規表現で読む形をやめたこと、新しいパス、chezmoi 側の変更が先に fox に入っている必要があることを書く。push は Task 3 で行う。

### Task 2: キーのファイルを配り、kiro.sh を消す（chezmoi）

**Files:**
- Create: `dot_config/cloudfront-waf-report/private_kiro-api-key.tmpl`
- Delete: `dot_config/environment/private_kiro.sh.tmpl`
- Modify: `.chezmoiignore`、`.chezmoiremove`、`AGENTS.md`（1Password の節の最後の項目）
- Test: `tests/test_zprofile_path.py`

**Interfaces:**
- Produces: fox の `~/.config/cloudfront-waf-report/kiro-api-key`（0600、値 1 行）。Task 1 のスクリプトが読む。

- [ ] **Step 1: テストを書き換える**

`test_startup_files_hold_no_secrets` のループを `("gitlab", "teslamate")` にする。新しいテスト `test_report_key_is_fox_only` を足し、次を確かめる。

- `dot_config/cloudfront-waf-report/private_kiro-api-key.tmpl` が `op://chezmoi/l2kqwiv5em4t4j2kxaat2py5fy/credential` を含み、`export` を含まない。
- `.chezmoiignore` の `{{- if ne .chezmoi.hostname "fox" }}` から次の `{{- end }}` までに `.config/cloudfront-waf-report` がある。
- `dot_config/environment/private_kiro.sh.tmpl` がない。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run python -m unittest tests.test_zprofile_path`
Expected: `test_report_key_is_fox_only` が FAIL

- [ ] **Step 3: 実装する**

テンプレートは `{{- onepasswordRead "op://chezmoi/l2kqwiv5em4t4j2kxaat2py5fy/credential" -}}` の 1 行だけにし、hostname の条件は持たせない。`.chezmoiignore` の末尾に `{{- if ne .chezmoi.hostname "fox" }}` のブロックを足して `.config/cloudfront-waf-report` を入れ、ブロックの前に既存と同じ `{{- /* ... */}}` 形式で「cloudfront-waf-report runs only on fox.」とコメントを書く。`git rm dot_config/environment/private_kiro.sh.tmpl` で消し、`.chezmoiremove` の末尾に「# The WAF report Kiro API key lives in ~/.config/cloudfront-waf-report/kiro-api-key.」と `.config/environment/kiro.sh` を足す。AGENTS.md の 1Password の節の最後の項目から `kiro.sh` の例外の文を消し、「Put a secret that only an unattended job reads in a key-only file under `dot_config/<job>/`, such as `dot_config/cloudfront-waf-report/private_kiro-api-key.tmpl`, and list the directory in `.chezmoiignore` for hosts that do not run the job.」に置き換える。

- [ ] **Step 4: テストと lint を通し、配布先を確かめる**

Run: `uvx pre-commit run --all-files` と `uv run python -m unittest discover -s tests`（新しいファイルを先に `git add` する）
Expected: どちらも成功

Run: `chezmoi --no-pager managed -i files | rg 'cloudfront-waf-report|environment/kiro'`
Expected: この Mac では何も出ない

- [ ] **Step 5: コミットする**

```bash
git add .chezmoiignore .chezmoiremove AGENTS.md dot_config/cloudfront-waf-report tests/test_zprofile_path.py
git commit -m "refactor: move the WAF report Kiro API key to a key-only file"
```

`git rm` した `private_kiro.sh.tmpl` も同じコミットに入る。本文には、`kiro.sh` がシェルに読まれず export 行の形の制約を抱えていたこと、新しいパス、ansible-playbooks の `cloudfront_waf_report` が対応したことを書く。push は Task 3 で行う。

### Task 3: fox で切り替えて確かめる

**Interfaces:**
- Consumes: Task 1 と Task 2 のコミット。

`ssh fox true` が通ってから始める。通らなければ、ここで止めて利用者に知らせる。

- [ ] **Step 1: chezmoi を push して fox に適用する**

`~/git/chezmoi` の `main` を push する。fox で `chezmoi update` を実行する。

Expected: fox で `stat -c '%a %U' ~/.config/cloudfront-waf-report/kiro-api-key` が `600 tats` を出し、`test -e ~/.config/environment/kiro.sh` が失敗する

- [ ] **Step 2: ansible-playbooks を main に入れて fox に適用する**

worktree で spec とこの plan を `docs/superpowers/archive/specs/` と `docs/superpowers/archive/plans/` の同じ名前に移し、`docs: archive the WAF report Kiro key file spec and plan` でコミットする。リモートの main を fetch し直して fast-forward できることを確かめてから、`feat/waf-report-kiro-key` をリモートの main に push する。ローカルの `main` と `feat/mailboxd` には触れない。

Run（Mac の worktree で）: `direnv exec . ansible-playbook home-primary.yml --tags cloudfront_waf_report --limit fox --check --diff`、続けて `--check` を外した同じコマンド
Expected: 差分は `config.json` の `kiro_api_key_file` の行とスクリプトだけ。終了コード 0

- [ ] **Step 3: キーが読めることを確かめる**

Run（fox で）: `sudo -u tats cloudfront-waf-report --dry-run`
Expected: 件名が「AI 判定なし」で終わらない。

スクリプトは候補があるときだけキーを読むので、件名が「対応不要」の週は次も実行する。

Run（fox で）: `sudo -u tats sh -c 'tr -d "[:space:]" < ~/.config/cloudfront-waf-report/kiro-api-key | wc -c'`
Expected: 0 より大きい数（値は出さない）

- [ ] **Step 4: worktree を片付ける**

`git worktree remove /tmp/ap-waf-kiro-key` を実行し、`git branch -d feat/waf-report-kiro-key` でブランチを消す。
