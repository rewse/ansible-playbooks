# gnucash データベースの rewse-pg 統合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gnucash` データベースを Aurora クラスタ `gnucash-db` から `rewse-pg` に移し、接続名を `rewse-pg.rewse.jp` に揃え、オフィスからは alfa 経由の SSH トンネルでつなげるようにする。

**Architecture:** 先に expense フォームを `quick-expense` 以外のユーザー名で DB に接続しないようにする。そのあと fox から pg_dump と pg_restore で移し、旧クラスタを止めて DNS を消す。最後に Ansible、1Password、chezmoi、gnucash-import-agent の接続先を切り替える。

**Tech Stack:** Aurora PostgreSQL 16.11、psql/pg_dump 16.15(fox)、AWS CLI、1Password CLI、Ansible、Python 3(Starlette、pytest)、chezmoi。

**Spec:** `docs/superpowers/specs/2026-11-11-gnucash-db-merge-design.md`

## Global Constraints

- AWS への書き込みは `--profile admin --region ap-northeast-1`、読み取りは既定のプロファイル(ReadOnly)で行う。
- 秘密の値は画面にも引数にも出さない。`op read` の出力はパイプで stdin に渡し、ssh 先では `IFS= read -r p; export PGPASSWORD="$p"` で受ける。`op item get` は `--fields` で非秘密の項目だけ読むか、ラベルと型だけを表示する。
- ansible vault はサービスアカウント(`direnv exec . op ...`)で読む。Private vault と gnucash vault の読み書き、ansible vault への書き込みは個人アカウント(`env -u OP_SERVICE_ACCOUNT_TOKEN op ...`)で行う。こちらは 1Password の承認が出る。
- 作業ディレクトリは `mktemp -d /tmp/gnucash-merge.XXXXXX` で作り、終わったら `command rm -rf` で消す。fox 上のダンプも同じ。
- DB への接続はすべて fox から行う。`sslmode=require` と `require_auth=scram-sha-256` を付ける。
- このホストから GitHub に push するときは github-push-via-fox スキルを使う。どのリポジトリも作業ブランチを切って PR にし、CI が通ってからマージする。
- コミットメッセージは Conventional Commits(英語)、スペックとプランは日本語の常体で書く。
- gnucash-quick-expense と gnucash-import-agent は public リポジトリなので、ホスト名、エンドポイント、個人のロール名をコード、テスト、文書に書かない。テストで使うユーザー名は `expense-form` とする。
- ansible-playbooks の適用は `--tags` で絞り、先に `--check --diff` で確かめる。適用は終了コードで判断し、2 回目の実行で `changed=0` になることも確かめる。
- 旧クラスタの削除(Task 8)は、利用者が改めて承認するまで実行しない。

## Review Focus

- 大文字小文字や空白だけが違うユーザー名(`Expense-Form`、`expense-form `)は、一覧にないものとして DB に接続せず 401 を返す。テストは Task 1 にある。
- 切り替え後に古い URI で開いた GnuCash は、名前解決に失敗して旧 DB に書き込まない。Task 4 で `dig` を使って確かめる。
- ダンプの時点で GnuCash を開いていたら(`gnclock` に行がある)、移行を止める。Task 4 Step 2 で止める。
- pg_restore が途中で失敗しても、旧クラスタと接続先はまだ変えていないので元に戻せる。`rewse-pg` に作りかけの `gnucash` データベースを DROP し、`gnucash-quick-expense` を起動し直す。Task 4 Step 4 に書いてある。
- `rewse-pg` の `muse` ロールから `gnucash` データベースを読める。`gnucash-db` 側の `muse` は廃止するので、この確認は Task 4 Step 5 にある。

---

### Task 1: gnucash-quick-expense にユーザー名の許可リストを足す

**Files:**
- Modify: `~/git/gnucash-quick-expense/src/gnucash_quick_expense/config.py`(`Config`、`load`)
- Modify: `~/git/gnucash-quick-expense/src/gnucash_quick_expense/app.py`(`create_app` の `with_session`)
- Modify: `~/git/gnucash-quick-expense/config.example.yaml`、`README.md` の Configuration 節
- Test: `~/git/gnucash-quick-expense/tests/test_config.py`、`tests/test_app.py`

**Interfaces:**
- Produces: `config.Config` に 3 番目のフィールド `users: frozenset[str]` を足す。YAML のトップレベルキーは `users` で、空でない文字列の空でないリストを必須とする。満たさなければ `ConfigError("users must be a non-empty list of strings")` を投げる。Task 2 の `config.yaml.j2` がこのキーを出力する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py`:
- `test_load_reads_the_example` に `assert loaded.users == frozenset({"expense-form"})` を足す。
- `test_load_allows_a_missing_default` の YAML に `users: [expense-form]\n` を足す。
- `test_load_rejects_invalid_files` に 4 ケースを足す。どれも `from_accounts` と `to_accounts` は正しく書く。
  - `missing-users`: `users` がない
  - `empty-users`: `users: []`
  - `user-not-a-string`: `users: [1]`
  - `user-empty-string`: `users: ['']`

`tests/test_app.py`:
- `CONFIG` の 3 番目の引数に `frozenset({"expense-form"})` を渡す。
- 次のテストを足す。

```python
@pytest.mark.parametrize("path", ["/api/accounts", "/api/rate", "/api/expenses"])
@pytest.mark.parametrize("user", ["postgres", "Expense-Form", "expense-form "])
def test_unlisted_username_is_401_without_connecting(calls, path, user):
    response = _post(_client(calls), path, username=user, **{"from": "Assets:Dollar:Cash", "to": "Expenses:Food:Dining"}, date="2026-10-30", amount="1", description="")
    assert response.status_code == 401
    assert response.json() == {"error": "Wrong username or password."}
    assert calls["connections"] == []
```

- [ ] **Step 2: 失敗を確かめる**

Run: `cd ~/git/gnucash-quick-expense && uv sync --extra test && uv run pytest tests/test_config.py tests/test_app.py -q`
Expected: 新しいテストが FAIL する(`users` 属性がない、または 200 が返る)。

- [ ] **Step 3: 実装する**

`config.load` で `users` を検証して `frozenset` にする。`with_session` では、`_text` で `username` と `password` を取り出した直後、`connect` を呼ぶ前に `if user not in cfg.users: raise db.AuthError()` を入れる。`config.example.yaml` と README の Configuration 節に、`users` の説明と `- expense-form` の例を足す。説明は「フォームがログインに使ってよい PostgreSQL ロール。一覧にない名前は DB に接続せず、パスワードが間違っているときと同じ扱いになる」。

- [ ] **Step 4: 単体テストと統合テストが通ることを確かめる**

Run: `container run -d --name gqe-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16`、続けて `GQE_TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/postgres uv run pytest -q`、続けて `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: すべて PASS。コンテナは確認後に `container rm -f gqe-pg` で消す。

- [ ] **Step 5: コミットして PR をマージする**

ブランチ `feat/username-allowlist` で `feat(config)!: require the usernames the form may sign in as` としてコミットする。本文には理由(公開フォームを DB のパスワード試行の窓口にしないため)を書き、フッターに `BREAKING CHANGE: config.yaml must list users.` を付ける。github-push-via-fox スキルで push し、PR の CI が通ったらマージする。

### Task 2: Ansible からユーザー名の一覧を渡して fox に反映する

**Files:**
- Modify: `roles/gnucash_quick_expense/vars/main.yml`
- Modify: `roles/gnucash_quick_expense/templates/config.yaml.j2`
- Test: `tests/test_gnucash_quick_expense.py`

**Interfaces:**
- Consumes: Task 1 の YAML キー `users`
- Produces: `gnucash_quick_expense_db_users: ["quick-expense"]`

- [ ] **Step 1: 失敗するテストを書く**

`test_config_lists_the_allowed_users`: `config.yaml.j2` を `to_json` フィルタ付きの jinja2 で `VARS` を使ってレンダリングし、`yaml.safe_load` した結果の `["users"]` が `["quick-expense"]` であることを確かめる。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_gnucash_quick_expense.py -q`
Expected: 新しいテストが FAIL する。

- [ ] **Step 3: 実装する**

作業ブランチ `feat/gnucash-db-merge` を切る。`vars/main.yml` に、変数とその理由のコメント(フォームは公開されているので、DB にログインしてよいのはこのロールだけにする)を足す。テンプレートでは、`patterns` と同じ書き方で `users:` のリストを出力する。

- [ ] **Step 4: テストと lint が通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q`、続けて `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: PASS。

- [ ] **Step 5: 適用して確かめる**

Run: `ansible-playbook home-primary.yml --tags gnucash_quick_expense_app,gnucash_quick_expense_service --check --diff`、続けて `--check` を外して実行する。
Expected: 終了コード 0。`/etc/gnucash-quick-expense/config.yaml` に `users` が入り、`systemctl is-active gnucash-quick-expense` が `active`。2 回目の実行で `changed=0`。

このホストから `https://expense.rewse.jp/api/accounts` に POST して確かめる。認証情報は stdin から `curl -K -` で渡す。
- `username` が `postgres`、パスワードがダミー: 401
- `quick-expense` と本物のパスワード(Private vault `evpsfx7fz4g4c7xh23nvgr5eni`): 200

fail2ban は 10 分に 5 回で遮断するので、401 を返す試行は 2 回までにする。

- [ ] **Step 6: コミットする**

最初にスペックとプランを `docs: add the gnucash-db merge spec and plan` としてコミットし、続けてロールの変更を `feat(gnucash_quick_expense): let the form sign in only as quick-expense` としてコミットする。

### Task 3: rewse-pg にロールを作る

**Files:** なし(DB の操作)。手元の作業ディレクトリに `scram.py` を置く。

**Interfaces:**
- Produces: `rewse-pg` のロール `gnucash`(LOGIN、`postgres` が所属)と `"quick-expense"`(LOGIN)。パスワードはそれぞれ ansible vault `wypbfjrqxkssvefhycefqcfn5y` と Private vault `evpsfx7fz4g4c7xh23nvgr5eni` のもの。

- [ ] **Step 1: 二つの `gnucash` 項目のパスワードが同じか確かめる**

Run: `cmp -s <(direnv exec . op read op://ansible/wypbfjrqxkssvefhycefqcfn5y/password) <(env -u OP_SERVICE_ACCOUNT_TOKEN op read op://gnucash/n4k5eoi3jxo7ynmsfxisls7liu/password) && echo same`
Expected: `same`。違う場合は、どちらを使うか利用者に聞いてから進む。

- [ ] **Step 2: SCRAM の検証子を作るスクリプトを置く**

`scram.py` は stdin の 1 行目をパスワードとして読み、`SCRAM-SHA-256$4096:<salt>$<StoredKey>:<ServerKey>` を出力する。ASCII 以外を含むパスワードは SASLprep が必要なので、エラーで止める。

```python
salt = os.urandom(16)
salted = hashlib.pbkdf2_hmac("sha256", pw, salt, 4096)
client_key = hmac.new(salted, b"Client Key", "sha256").digest()
server_key = hmac.new(salted, b"Server Key", "sha256").digest()
stored_key = hashlib.sha256(client_key).digest()
# base64 each part: f"SCRAM-SHA-256$4096:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"
```

- [ ] **Step 3: ロールを作る**

手元で SQL を組み立て、1 行目に `postgres` のパスワード(ansible vault `citpxpqr6evzwwndtzjugdoesi`)、2 行目以降に SQL を置いた stdin を ssh で fox に渡す。fox では `psql "host=rewse-pg.rewse.jp dbname=postgres user=postgres sslmode=require" -v ON_ERROR_STOP=1 -f -` で流す。SQL の中身は次のとおり。
- `CREATE ROLE gnucash LOGIN PASSWORD '<verifier>'`
- `GRANT gnucash TO postgres`
- `CREATE ROLE "quick-expense" LOGIN PASSWORD '<verifier>'`

- [ ] **Step 4: ログインできることを確かめる**

fox から、`gnucash` と `quick-expense` のそれぞれで `rewse-pg` の `postgres` データベースに `require_auth=scram-sha-256` を付けて接続し、`select current_user` を実行する。
Expected: どちらも自分のロール名が返る。

### Task 4: データを移して旧クラスタを切り離す(停止時間あり)

**Files:** なし(運用作業)。

**Interfaces:**
- Consumes: Task 2 で反映した許可リストと、Task 3 のロール
- Produces: `rewse-pg` の `gnucash` データベース、旧クラスタの手動スナップショット `gnucash-db-final-20261111`、停止した `gnucash-db`、消えた `gnucash-db.rewse.jp`

- [ ] **Step 1: 書き込みを止める**

Run: `ssh fox.rewse.jp sudo systemctl stop gnucash-quick-expense`
Expected: `systemctl is-active` が `inactive`。

- [ ] **Step 2: 誰も使っていないことを確かめる**

`gnucash-db` に `gnucash` で接続して確かめる。
- `select count(*) from gnclock` が 0
- `pg_stat_activity` で `datname = 'gnucash'` の接続が、確認に使っている自分の接続だけ

Expected: 両方満たす。満たさなければここで止め、Step 1 を戻して利用者に知らせる。

- [ ] **Step 3: ダンプを取る**

fox 上で `d=$(mktemp -d /tmp/gnucash-merge.XXXXXX)` を作る。`gnucash` として `pg_dump -Fc -C -h gnucash-db.rewse.jp -U gnucash -d gnucash -f "$d/gnucash.dump"` を実行する。
Expected: 終了コード 0、ファイルが空でない。

- [ ] **Step 4: rewse-pg に入れる**

`postgres` として `pg_restore -C --exit-on-error -h rewse-pg.rewse.jp -U postgres -d postgres "$d/gnucash.dump"` を実行する。
Expected: 終了コード 0。失敗したときは、`rewse-pg` で `DROP DATABASE IF EXISTS gnucash` を実行し、fox で `gnucash-quick-expense` を起動し直して利用者に知らせる。接続先はまだ旧クラスタのままなので、これで元に戻る。

- [ ] **Step 5: 新旧を比べる**

同じクエリを新旧の両方に流して `diff` する。
- `public` の全テーブルの件数
- `select max(enter_date) from transactions`
- `select datacl from pg_database where datname = 'gnucash'`
- `information_schema.role_table_grants` の `grantee`、`table_name`、`privilege_type`

`rewse-pg` では、さらに次を確かめる。`muse`(ansible vault `wi3josvnu5dujxoosdh74igisq`)で `select count(*) from transactions` が実行できる。`quick-expense` で `gnucash` データベースに接続できる。

Expected: `diff` が空。件数は事前調査の時点で `transactions` 44603、最新の `enter_date` は 2026-11-08 10:14:34。datacl は `{gnucash=CTc/gnucash,"\"quick-expense\"=c/gnucash",muse=c/gnucash}`。

- [ ] **Step 6: ダンプを消す**

Run: fox で `command rm -rf "$d"`

- [ ] **Step 7: スナップショットを取って旧クラスタを止める**

Run: `aws rds create-db-cluster-snapshot --db-cluster-identifier gnucash-db --db-cluster-snapshot-identifier gnucash-db-final-20261111`。`aws rds wait db-cluster-snapshot-available` で待ってから `aws rds stop-db-cluster --db-cluster-identifier gnucash-db` を実行する(どちらも admin プロファイル)。
Expected: スナップショットが `available` になり、クラスタが `stopped` になる。

- [ ] **Step 8: DNS の名前を消す**

Route53 のゾーン `Z2I4KTTS0XIOSB` から、`gnucash-db.rewse.jp.` の CNAME(TTL 300、値 `gnucash-db.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com`)を、admin プロファイルの `change-resource-record-sets` で DELETE する。
Expected: TTL が切れたあと、このホストと fox の両方で `dig +short gnucash-db.rewse.jp` が空になる。

### Task 5: Ansible と 1Password の接続先を切り替える

**Files:**
- Modify: `roles/muse/vars/main.yml`(`muse_pgpass_entries` から `gnucash-db.rewse.jp` の要素を消す)
- Modify: `roles/muse/tasks/pgpass.yml`(最後にタスク `pgpass | Remove gnucash-db entry` を足す。`lineinfile` で `regexp: '^gnucash-db\.rewse\.jp:'`、`state: absent`)

- [ ] **Step 1: ansible vault の項目を書き換える**

Run: `env -u OP_SERVICE_ACCOUNT_TOKEN op item edit wypbfjrqxkssvefhycefqcfn5y --vault ansible --title "PostgreSQL - gnucash" server=rewse-pg.rewse.jp`
Expected: `direnv exec . op read op://ansible/wypbfjrqxkssvefhycefqcfn5y/server` が `rewse-pg.rewse.jp` を返す。

- [ ] **Step 2: muse の pgpass を直してテストと lint を通す**

Run: `uv run --with pytest --with ansible-core pytest tests -q`、続けて `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: PASS。

- [ ] **Step 3: 適用して確かめる**

Run: `ansible-playbook home-primary.yml --tags gnucash_quick_expense_service,muse_pgpass` と `ansible-playbook home-secondary.yml --tags muse_pgpass`。どちらも先に `--check --diff` で確かめる。
Expected:
- 終了コード 0
- fox の `/etc/gnucash-quick-expense/env` が `GQE_DB_HOST=rewse-pg.rewse.jp` になり、サービスが `active`
- 両ホストの `/home/muse/.config/pg/pgpass` に `gnucash-db.rewse.jp` で始まる行がない
- 2 回目の実行で `changed=0`
- `https://expense.rewse.jp/api/accounts` に `quick-expense` で POST すると 200 が返り、勘定科目の一覧が返る

- [ ] **Step 4: コミットし、古い行を消すタスクを外す**

`fix(muse): drop the gnucash-db pgpass entry` としてコミットする。両ホストに反映済みなので、続けて `pgpass | Remove gnucash-db entry` を消し、`chore(muse): remove the converged gnucash-db pgpass cleanup` としてコミットする。

- [ ] **Step 5: gnucash-db 用の muse の項目をアーカイブする**

Run: `env -u OP_SERVICE_ACCOUNT_TOKEN op item delete bfw2z4gziah6gnt44v7hl7k22q --vault ansible --archive`
Expected: `op item get bfw2z4gziah6gnt44v7hl7k22q --vault ansible` が見つからないエラーになる。

### Task 6: オフィスから alfa 経由でつなぐ

**Files:**
- Modify: `~/git/chezmoi/private_dot_ssh/config.tmpl`(`Host alfa` に `LocalForward 15432 rewse-pg.rewse.jp:5432` を足す)

- [ ] **Step 1: 反映してトンネルを張る**

Run: `chezmoi apply ~/.ssh/config`、続けて `ssh -fN alfa`
Expected: `lsof -nP -iTCP:15432 -sTCP:LISTEN` に表示されるのが `127.0.0.1`(と `[::1]`)だけ。

- [ ] **Step 2: 証明書の検証がトンネル越しに通ることを確かめる**

Run: `openssl s_client -starttls postgres -connect 127.0.0.1:15432 -servername rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com -verify_hostname rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com -CAfile ~/.postgresql/rds-global-bundle.pem </dev/null`
Expected: 出力に `Verify return code: 0 (ok)` がある。確認したらトンネルの ssh を終了する。

- [ ] **Step 3: コミットして PR をマージする**

ブランチを切り、`feat(ssh): forward rewse-pg through alfa` としてコミットする。github-push-via-fox スキルで push し、PR をマージする。

### Task 7: gnucash-import-agent の接続先と手順を直す

**Files:**
- Modify: `~/git/gnucash-import-agent/.agents/skills/gnucash-import/SKILL.md`
- Test: `~/git/gnucash-import-agent/tests/test_skill_docs.py`

- [ ] **Step 1: 失敗するテストを書く**

`test_database_item_is_read_by_id`: SKILL.md に `op://gnucash/gnucash-db/` が含まれず、`op://gnucash/n4k5eoi3jxo7ynmsfxisls7liu/server` が含まれることを確かめる。

- [ ] **Step 2: 失敗を確かめる**

Run: `python3 -m unittest tests.test_skill_docs -v`
Expected: 新しいテストが FAIL する。

- [ ] **Step 3: SKILL.md を直す**

`op://gnucash/gnucash-db/` をすべて `op://gnucash/n4k5eoi3jxo7ynmsfxisls7liu/` に置き換える。84 行目の説明は、DB には自宅の VPN からしか届かず、ほかの場所からは SSH のローカルポートフォワードを使う、という内容に直す。トンネルを使うときの手順も足す。`DB_HOST` はエンドポイント名のまま残し、`DB_PORT` を転送したポートに、`PGHOSTADDR=127.0.0.1` を psql の行に付ける。こうすれば `verify-full` はエンドポイント名で証明書を検証できる。新しく書く psql の行にも `PGSSLMODE=verify-full` を付ける。ホスト名、エンドポイント、ポート番号の実際の値は書かない。

- [ ] **Step 4: テストと lint が通ることを確かめる**

Run: `python3 -m unittest discover -s tests`、続けて `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`、続けて `git diff --check`
Expected: PASS。

- [ ] **Step 5: 項目を書き換える**

Run: `env -u OP_SERVICE_ACCOUNT_TOKEN op item edit n4k5eoi3jxo7ynmsfxisls7liu --vault gnucash --title "PostgreSQL - gnucash" server=rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com`
Expected: `op read op://gnucash/n4k5eoi3jxo7ynmsfxisls7liu/server` が新しいエンドポイント名を返す。

- [ ] **Step 6: コミットして PR をマージする**

ブランチを切り、`fix(skill): read the database item by ID and document tunnel access` としてコミットする。github-push-via-fox スキルで push し、PR をマージする。

### Task 8: 仕上げ(利用者の確認と旧クラスタの削除)

- [ ] **Step 1: 利用者に作業を頼む**

次の二つを頼む。
- 各 Mac の GnuCash を開き直す。自宅では `postgres://gnucash@rewse-pg.rewse.jp/gnucash`、オフィスでは `ssh -N alfa` を張って `postgres://gnucash@localhost:15432/gnucash`。
- Muse のコネクタやプロンプトに `gnucash-db.rewse.jp` があれば直す。

- [ ] **Step 2: ansible-playbooks の PR をマージする**

このスペックとプランを `docs/superpowers/archive/specs/` と `docs/superpowers/archive/plans/` に移し、`docs: archive the gnucash-db merge spec and plan` としてコミットする。全体を確かめるために `ansible-playbook home-primary.yml --check` を実行し、終了コードが 0 であることを確かめる。AGENTS.md の Validation のとおり pre-commit と pytest を通してから、github-push-via-fox スキルで `feat/gnucash-db-merge` を push し、PR の CI が通ったらマージする。

- [ ] **Step 3: 旧クラスタを消す(利用者が改めて承認してから)**

旧クラスタを消すと元に戻せないので、利用者の承認を得てから実行する。手順は次のとおり(すべて admin プロファイル)。
1. `start-db-cluster` で起動する。停止中は設定を変えられないため。
2. `available` になったら `modify-db-cluster --no-deletion-protection --apply-immediately` で削除保護を外す。
3. `delete-db-instance --db-instance-identifier gnucash-db-1c` でインスタンスを消す。
4. `delete-db-cluster --db-cluster-identifier gnucash-db --skip-final-snapshot` でクラスタを消す。スナップショットは Task 4 Step 7 で取ってある。

Aurora は停止から 7 日で自動的に起動するので、承認が 2026-11-18 より後になる場合は、もう一度 `stop-db-cluster` する。
Expected: `describe-db-clusters` に `gnucash-db` がなく、スナップショット `gnucash-db-final-20261111` は残っている。
