# calendar-mcp 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox で MarimerLLC/calendar-mcp を ts と ubiqu の一人一つずつ動かし、Muse から iCloud のカレンダーと連絡先、Sakura のメールを使えるようにする。メールは下書きまでで、送信と配信停止はできない。最後に mailboxd を撤去する。

**Architecture:** `aged_release` で上流の `Release x.y.z` のコミットを選び、fox で checkout、下書きのパッチ、ビルドを行う。新しいロール `calendar_mcp` が Compose で二つのコンテナを `127.0.0.1:8084` と `127.0.0.1:8085` に立て、Apache の vhost `calendar-mcp.rewse.jp` が `/mcp/ts` と `/mcp/ubiqu` だけを流す。Quick Tunnel で Muse から確かめてから、CloudFront、UniFi の DNS、security-agent を入れる。

**Tech Stack:** Ansible（community.docker）、Docker Compose、.NET 10（上流）、MSTest（パッチのテスト）、Apache、fail2ban、1Password CLI、pytest と unittest + jinja2

**Spec:** `docs/superpowers/specs/2026-11-07-calendar-mcp-design.md`

**改訂（2026-11-07）:** 設計を fork 方式に改めた。Task 2 のパッチと Task 3 のパッチの適用は、Task 12（fork に三つの変更をテスト付きで積む）と Task 13（ロールを fork からのビルドに切り替える）で置き換える。Task 12 と 13 は Task 8 より前に行う。

## Global Constraints

- ロール名 `calendar_mcp`、ホスト名 `calendar-mcp.rewse.jp`、Compose プロジェクト `/etc/compose/calendar_mcp/compose.yaml`（`name: calendar_mcp`）、データ `/srv/calendar_mcp/<名前>`、checkout `/usr/local/src/calendar-mcp`
- 利用者は `ts`（`127.0.0.1:8084`）と `ubiqu`（`127.0.0.1:8085`）。fox で 8080 から 8083 は使用中、8084 と 8085 は空き。fox は aarch64
- 上流: `https://github.com/MarimerLLC/calendar-mcp.git`、`lookup('aged_release', 'github-commit:MarimerLLC/calendar-mcp', message='^Release (\d+\.\d+\.\d+)')`
- アカウント ID は `<名前>-sakura`（IMAP）と `<名前>-icloud`（DAV）
- `Permissions` は全アカウントに六つのフラグすべてを明示する。IMAP は `emailRead` だけ true、DAV は `calendarRead`、`calendarWrite`、`contactsRead`、`contactsWrite` だけ true。`emailSend` はどこでも false
- IMAP: `imapHost: rewse.sakura.ne.jp`、`imapPort: "993"`、`smtpHost: smtp.invalid`。DAV: `preset: icloud`、`enableCalendar: "true"`、`enableContacts: "true"`
- `ExternalBaseUrl: https://calendar-mcp.rewse.jp/mcp/<名前>`。Router と `AdminAuth` は書かない
- 秘密の置き場所: `CALENDAR_MCP_MCP_KEY` と `CALENDAR_MCP_ADMIN_TOKEN` は `/etc/compose/calendar_mcp/<名前>.env`（root、`"0600"`、`format: raw`）。パスワードと App 用パスワードは `/etc/compose/calendar_mcp/<名前>/appsettings.json`（コンテナの uid、`"0400"`、`/app/data/appsettings.json` に `:ro` でマウント）。Ansible が書く設定は `/etc/compose/<role>/`（mailboxd の `config.yaml` と同じ）、コンテナが書く状態は `/srv/<role>/` に分ける
- 外から届くパスは `/mcp/ts` と `/mcp/ubiqu` の完全一致だけ。`/health/<名前>` は `networks` の家、VPN、オフィスからだけ。それ以外は `Require all denied`
- 公開リポジトリなので、メールアドレス、Apple ID、1Password の項目名をコミットしない。コミットするのは項目 ID だけ
- AGENTS.md の Ansible の規約（`roles/filebrowser` と `roles/mailboxd` が手本）、タグ、タスク名、変数の接頭辞に従う
- コミットの前に `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests` を通す。新しいファイルは先に `git add` する
- 作業はメインの clone のブランチ `feat/calendar-mcp` で行う（`.envrc` がリポジトリの直下にあり、worktree では読めない）

## Review Focus

- ts のトークンで `/mcp/ubiqu` を呼ぶ、または `accountId` に `ubiqu-sakura` を渡す。前者は 401、後者は存在しないアカウントとして拒否されること（Task 7 Step 4）
- `/mcp/ts/`（末尾のスラッシュ）、`/mcp/ts/admin/ui`、`/mcp/ts/attachments`、`/mcp/kyn` のような完全一致でないパス。どれも 403 で、コンテナに届かないこと（Task 6 のテスト）
- 上流の新しい Release でパッチが当たらない。古いイメージのまま動き続け、play は失敗で終わること（Task 3 のテスト）
- パッチの内容だけを変えたとき。上流のコミットが同じでもイメージを作り直すこと（Task 3 のテスト、タグにパッチのハッシュを入れる）
- 引用符、バックスラッシュ、`$` を含むパスワード。`appsettings.json` が正しい JSON のままで、`.env` の値も変わらないこと（Task 4 のテスト）

---

### Task 1: `aged_release` の `message`

**Files:**
- Modify: `plugins/lookup/aged_release.py`（`DOCUMENTATION`、`_commit`、`resolve`、`LookupModule.run`）
- Test: `tests/test_aged_release.py`

**Interfaces:**
- Produces: `lookup('aged_release', 'github-commit:<owner>/<repo>', message='<regex>')` が `{'version': '<最初のグループ>', 'commit': '<sha>'}` を返す。`message` がなければ今までどおり `{'commit': '<sha>'}`
- Produces: `resolve(term, *, pattern, days, platform, asset, run, now, message=None)`

- [ ] **Step 1: ブランチを作る**

Run: `git switch -c feat/calendar-mcp`

- [ ] **Step 2: 失敗するテストを書く**

`FakeRun` のキーは `gh api repos/o/r/commits?sha=master&until=<iso(ago(4))>&per_page=100`。コミットの要素は `{"sha": ..., "commit": {"message": ...}}` で、API と同じく新しい順に並べる。

```python
def test_commit_message_selects_newest_matching_release():
    # commits: "Fix typo" (a), "Release 1.9.0 (#115)\n\nbody" (b), "Release 1.8.4 (#114)" (c)
    assert resolve("github-commit:o/r", run, message=r"^Release (\d+\.\d+\.\d+)") == {
        "version": "1.9.0",
        "commit": "b",
    }

def test_commit_message_matches_only_the_subject_line():
    # The only commit is "Merge branch x\n\nRelease 2.0.0".
    with pytest.raises(AnsibleLookupError, match="no commit"):
        resolve("github-commit:o/r", run, message=r"^Release (\d+\.\d+\.\d+)")

def test_commit_message_without_match_raises():
    # commits: "Fix typo" only.
    with pytest.raises(AnsibleLookupError, match="no commit"):
        resolve("github-commit:o/r", run, message=r"^Release (\d+\.\d+\.\d+)")

def test_commit_message_is_part_of_the_cache_key(monkeypatch, tmp_path):
    # LookupModule().run with and without message for the same term returns
    # different results, using the cache setup of test_lookup_caches_identical_calls.
    ...
```

`test_commit_returns_newest_aged` は変えずに通ること。

- [ ] **Step 3: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_aged_release.py -v`
Expected: 新しい四つが FAIL（`unexpected keyword argument 'message'` など）

- [ ] **Step 4: 実装する**

`message` があるときは `per_page=100` の一ページを読み、各コミットの題（`commit.message` の一行目）に `re.search` で当て、最初に一致したものの `group(1)` と `sha` を返す。一致がなければ `AnsibleLookupError(f"no commit of {repo} on {branch} matching {message} is at least {days} day(s) old")`。`LookupModule.run` は `kwargs.get("message")` を読み、キャッシュのキーに足す。`DOCUMENTATION` の `options` に `message` を書く。

- [ ] **Step 5: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_aged_release.py -v`
Expected: PASS

- [ ] **Step 6: 実物で確かめる**

Run: `direnv exec . ansible localhost -m debug -a "msg={{ lookup('aged_release', 'github-commit:MarimerLLC/calendar-mcp', message='^Release (\\d+\\.\\d+\\.\\d+)', days=4) }}"`
Expected: `version` が `1.9.0` 以上、`commit` が 40 文字の SHA

- [ ] **Step 7: Commit**

```bash
git add plugins/lookup/aged_release.py tests/test_aged_release.py
git commit -m "feat(aged_release): select a commit by a subject pattern"
```

### Task 2: 下書きのパッチ

上流の作業用 clone で変更とテストを書き、差分をロールのファイルにする。

**Files:**
- Create: `roles/calendar_mcp/files/save-draft.patch`
- 上流の中で変えるファイル（パッチに入る）:
  - Create: `src/CalendarMcp.Core/Tools/SaveDraftTool.cs`
  - Modify: `src/CalendarMcp.Core/Services/IProviderService.cs`
  - Modify: `src/CalendarMcp.Core/Providers/ImapProviderService.cs`
  - Modify: `src/CalendarMcp.HttpServer/Program.cs`（`.WithTools<CalendarMcp.Core.Tools.SaveDraftTool>()` を `MoveEmailTool` の次に）
  - Modify: `src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`

**Interfaces:**
- Consumes: Task 1 Step 6 の `commit`
- Produces: MCP ツール `save_draft(accountId, to, subject, body, bodyFormat = "html", cc = null, inReplyToEmailId = null)`。返り値は `{success, accountId, draftEmailId, message}` の JSON
- Produces: `IProviderService.SaveDraftAsync(string accountId, string to, string subject, string body, string bodyFormat = "html", List<string>? cc = null, string? inReplyToEmailId = null, CancellationToken cancellationToken = default)`、返り値 `Task<string?>`（保存した下書きのメール ID）。既定の実装は `NotSupportedException` を投げる
- Produces: `internal static MimeMessage ImapProviderService.BuildDraftMessage(string from, string to, List<string>? cc, string subject, string body, string bodyFormat, string? inReplyToMessageId, IEnumerable<string>? references)`。パッチを小さく保ち上流の変更とぶつかりにくくするため、`SendEmailAsync` の組み立てとは共有しない

- [ ] **Step 1: 上流を選んだコミットで clone する**

Run: `d=$(mktemp -d /tmp/calmcp-patch.XXXXXX) && git clone -q https://github.com/MarimerLLC/calendar-mcp.git "$d/src" && git -C "$d/src" checkout -q <commit>`

- [ ] **Step 2: 失敗するテストを書く**

`ImapProviderServiceTests.cs` に足す。

```csharp
[TestMethod]
public void BuildDraftMessage_SetsHeadersAndUtf8Body()
{
    var m = ImapProviderService.BuildDraftMessage(
        "me@example.com", "a@example.com, b@example.com", null,
        "件名テスト", "本文テスト", "text", null, null);
    Assert.AreEqual("me@example.com", m.From.Mailboxes.Single().Address);
    CollectionAssert.AreEqual(new[] { "a@example.com", "b@example.com" },
        m.To.Mailboxes.Select(x => x.Address).ToArray());
    Assert.AreEqual("件名テスト", m.Subject);
    Assert.AreEqual("本文テスト", ((TextPart)m.Body).Text);
    Assert.IsTrue(((TextPart)m.Body).IsPlain);
}

[TestMethod]
public void BuildDraftMessage_ThreadsAReply()
{
    var m = ImapProviderService.BuildDraftMessage(
        "me@example.com", "a@example.com", null, "Re: x", "<p>y</p>", "html",
        "orig@example.com", new[] { "root@example.com", "orig@example.com" });
    Assert.AreEqual("orig@example.com", m.InReplyTo);
    CollectionAssert.AreEqual(new[] { "root@example.com", "orig@example.com" }, m.References.ToArray());
    Assert.IsTrue(((TextPart)m.Body).IsHtml);
}
```

- [ ] **Step 3: 失敗を確かめる**

Run: `container run --rm -v "$d/src":/src -w /src mcr.microsoft.com/dotnet/sdk:10.0 dotnet test src/CalendarMcp.Tests --filter BuildDraftMessage`
Expected: ビルドエラー（`BuildDraftMessage` がない）

- [ ] **Step 4: 実装する**

- `ImapProviderService.SaveDraftAsync`: `ResolveConfigAsync` で設定を読む。返信元があれば `ParseEmailId` でフォルダーと UID を取り、`Message-Id` と `References` を読む。`BuildDraftMessage` で組み立て、`WithImapAsync` の中で `GetSpecialFolder(client, SpecialFolder.Drafts)` に `MessageFlags.Draft | MessageFlags.Seen` で APPEND する。Drafts が見つからなければ `InvalidOperationException`。APPEND が返す UID と `UidValidity` から `FormatEmailId` で ID を返し、UID が返らなければ null
- `SaveDraftTool`: `MoveEmailTool` と同じ形。権限は `ToolGuard.RequireAccountAsync(accountRegistry, accountId, AccountPermission.EmailRead)`。説明文に、下書きを保存するだけで送信しないことを書く
- SMTP には触れない

- [ ] **Step 5: 通ることを確かめる**

Run: `container run --rm -v "$d/src":/src -w /src mcr.microsoft.com/dotnet/sdk:10.0 dotnet test src/CalendarMcp.Tests`
Expected: すべて PASS（上流のテストを含む）

- [ ] **Step 6: パッチにする**

Run: `git -C "$d/src" add -A && git -C "$d/src" diff --cached > roles/calendar_mcp/files/save-draft.patch`
確認: `git -C "$d/src" stash && git -C "$d/src" apply --check "$PWD/roles/calendar_mcp/files/save-draft.patch"` が何も出さずに終わる

- [ ] **Step 7: Commit**

```bash
git add roles/calendar_mcp/files/save-draft.patch
git commit -m "feat(calendar_mcp): add a save_draft tool patch for the IMAP provider"
```

### Task 3: source コンポーネント

**Files:**
- Create: `roles/calendar_mcp/tasks/main.yml`、`roles/calendar_mcp/tasks/source.yml`、`roles/calendar_mcp/vars/main.yml`、`roles/calendar_mcp/meta/main.yml`（`fail2ban` と `httpd` に依存、mailboxd と同じ）
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: Task 1 の `lookup`、Task 2 のパッチ
- Produces: `__calendar_mcp_image`（文字列 `calendar-mcp:<version>-<commit[:7]>-<パッチの sha256 の先頭 8 文字>`）。Task 5 の compose が使う
- Produces: `vars/main.yml` の `calendar_mcp_hostname`、`calendar_mcp_source_dir`、`calendar_mcp_data_dir`、`calendar_mcp_users`（`name`、`port`、`sakura_item`、`apple_item`、`token_item` の辞書のリスト。ts の `sakura_item` は `scuhuvks3pdlwlgkvnzlaptyke`、ubiqu は `2eb4e5qbwgl555366yquo3wufy`。`apple_item` と `token_item` は Task 7 で埋めるまで空文字）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_calendar_mcp.py` に `test_mailboxd.py` と同じ `role_vars`、`render`、`task_named` の補助を置き、次を書く。

```python
class CalendarMcpSourceTest(unittest.TestCase):
    def test_lookup_selects_release_commits(self):
        fact = task_named("source.yml", "source | Resolve aged release")["ansible.builtin.set_fact"]
        self.assertIn("github-commit:MarimerLLC/calendar-mcp", fact["__calendar_mcp_source"])
        self.assertIn(r"^Release (\d+\.\d+\.\d+)", fact["__calendar_mcp_source"])

    def test_image_tag_changes_with_the_patch(self):
        fact = task_named("source.yml", "source | Name image")["ansible.builtin.set_fact"]
        self.assertIn("save-draft.patch", fact["__calendar_mcp_image"])
        self.assertIn("hash('sha256')", fact["__calendar_mcp_image"])

    def test_build_is_skipped_when_the_image_exists(self):
        for name in ("source | Check out repository", "source | Apply patch", "source | Build image"):
            self.assertIn("__calendar_mcp_image_info.images", str(task_named("source.yml", name)["when"]))

    def test_patch_failure_stops_the_play(self):
        task = task_named("source.yml", "source | Apply patch")
        self.assertNotIn("ignore_errors", task)
        self.assertNotIn("failed_when", task)

    def test_users_and_ports(self):
        users = role_vars()["calendar_mcp_users"]
        self.assertEqual([u["name"] for u in users], ["ts", "ubiqu"])
        self.assertEqual([u["port"] for u in users], [8084, 8085])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: FAIL（ロールがない）

- [ ] **Step 3: 実装する**

`source.yml` は次の順に並べる。`Resolve aged release`、`Name image`、`Read image`（`community.docker.docker_image_info`、`register: __calendar_mcp_image_info`）、`Deploy patch`（`files/save-draft.patch` を `/usr/local/src/calendar-mcp.patch` に `copy`）、`Check out repository`（`ansible.builtin.git`、`force: true`）、`Apply patch`（`git apply` の `command`、`chdir` を checkout に）、`Build image`（`community.docker.docker_image_build`、`path: "{{ calendar_mcp_source_dir }}"`、`name` と `tag` は `__calendar_mcp_image` を分けて渡す）。checkout、パッチ、ビルドは `__calendar_mcp_image_info.images | length == 0` のときだけ動かす。checkout は check mode で中身を作らないので、パッチとビルドは check mode で飛ばし、`debug`（`verbosity: 0`）で理由を出す。`main.yml` は `source.yml` を `calendar_mcp_source` と `update` のタグで import する。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): build the image from the newest aged release with the draft patch"
```

### Task 4: config コンポーネント

**Files:**
- Create: `roles/calendar_mcp/tasks/config.yml`、`roles/calendar_mcp/templates/appsettings.json.j2`、`roles/calendar_mcp/templates/env.j2`
- Modify: `roles/calendar_mcp/tasks/main.yml`、`roles/calendar_mcp/vars/main.yml`（`calendar_mcp_uid`、`calendar_mcp_sakura_folders`）
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: `calendar_mcp_users`
- Produces: `__calendar_mcp_accounts`（`name`、`port`、`address`、`sakura_password`、`apple_id`、`apple_password`、`token`、`admin_token` の辞書のリスト、`no_log`）。テンプレートは一人分を `account` という変数で描画する
- Produces: `/etc/compose/calendar_mcp/<名前>/appsettings.json` と `/etc/compose/calendar_mcp/<名前>.env`。変わったら `Recreate calendar-mcp` を通知する

- [ ] **Step 1: Sakura のフォルダー名を調べる**

`sentFolder`、`trashFolder`、`junkFolder` の既定値は Gmail 向けなので、Sakura の実際の名前を読む。mailboxd が動いているうちに、fox で ts のトークンを使って mailboxd のフォルダー一覧の道具を呼ぶ。トークンは `op read` からパイプで渡し、表示しない。送信済み、ゴミ箱、迷惑メールの名前を `calendar_mcp_sakura_folders`（キー `sent`、`trash`、`junk`）に書く。

- [ ] **Step 2: uid を調べる**

Run（fox）: `docker run --rm mcr.microsoft.com/dotnet/aspnet:10.0 sh -c 'groupadd -r mcpuser && useradd -r -g mcpuser -d /app -s /sbin/nologin mcpuser && id -u mcpuser'`
上流の Dockerfile と同じ手順で作る uid を `calendar_mcp_uid` に書き、Task 7 でビルドしたイメージの `docker run --rm --entrypoint id calendar-mcp:<tag> -u` と一致することを確かめる。

- [ ] **Step 3: 失敗するテストを書く**

```python
ACCOUNT = {"name": "alice", "port": 8084, "address": "alice@example.com",
           "sakura_password": "s-pass", "apple_id": "alice@icloud.com",
           "apple_password": "aaaa-bbbb-cccc-dddd", "token": "t", "admin_token": "a"}

class CalendarMcpConfigTest(unittest.TestCase):
    def settings(self, account=ACCOUNT):
        return json.loads(render("appsettings.json.j2", account=account))["CalendarMcp"]

    def test_exactly_two_accounts_with_explicit_permissions(self):
        accounts = self.settings()["Accounts"]
        self.assertEqual([(a["Id"], a["Provider"]) for a in accounts],
                         [("alice-sakura", "imap"), ("alice-icloud", "dav")])
        flags = {"emailRead", "emailSend", "calendarRead", "calendarWrite", "contactsRead", "contactsWrite"}
        for a in accounts:
            self.assertEqual(set(a["Permissions"]), flags)
            self.assertIs(a["Permissions"]["emailSend"], False)

    def test_imap_reads_mail_only(self):
        imap = self.settings()["Accounts"][0]
        self.assertEqual({k for k, v in imap["Permissions"].items() if v}, {"emailRead"})
        self.assertEqual(imap["ProviderConfig"]["imapHost"], "rewse.sakura.ne.jp")
        self.assertEqual(imap["ProviderConfig"]["smtpHost"], "smtp.invalid")

    def test_dav_has_calendar_and_contacts_only(self):
        dav = self.settings()["Accounts"][1]
        self.assertEqual({k for k, v in dav["Permissions"].items() if v},
                         {"calendarRead", "calendarWrite", "contactsRead", "contactsWrite"})
        self.assertEqual(dav["ProviderConfig"]["preset"], "icloud")

    def test_no_router_and_no_admin_sign_in(self):
        root = json.loads(render("appsettings.json.j2", account=ACCOUNT))
        self.assertNotIn("Router", root["CalendarMcp"])
        self.assertNotIn("AdminAuth", root)

    def test_external_url_is_the_https_path(self):
        self.assertEqual(self.settings()["ExternalBaseUrl"], "https://calendar-mcp.rewse.jp/mcp/alice")

    def test_odd_password_stays_intact(self):
        odd = dict(ACCOUNT, sakura_password='a"b\\c$d', token='x$y')
        imap = self.settings(odd)["Accounts"][0]
        self.assertEqual(imap["ProviderConfig"]["password"], 'a"b\\c$d')
        self.assertIn("CALENDAR_MCP_MCP_KEY=x$y", render("env.j2", account=odd).splitlines())

    def test_env_carries_only_the_two_keys(self):
        lines = [l for l in render("env.j2", account=ACCOUNT).splitlines() if l and not l.startswith("#")]
        self.assertEqual(lines, ["CALENDAR_MCP_MCP_KEY=t", "CALENDAR_MCP_ADMIN_TOKEN=a"])

    def test_secret_files_are_private(self):
        self.assertEqual(task_named("config.yml", "config | Deploy settings")["ansible.builtin.template"]["mode"], "0400")
        self.assertEqual(task_named("config.yml", "config | Deploy environment file")["ansible.builtin.template"]["mode"], "0600")
```

`render` に `to_json` フィルターを `json.dumps` で与える。テンプレートは値を `| to_json` で書く。

- [ ] **Step 4: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: 新しいテストが FAIL

- [ ] **Step 5: 実装する**

`config.yml` は mailboxd の `config | Resolve mailboxes` と同じ形で `__calendar_mcp_accounts` を作る。Sakura と Apple の項目からは `username` と `password`、トークンの項目からは `credential` と `admin token` を読む。`appsettings.json` と `.env` は `loop` で一人ずつ描画する。`appsettings.json` の所有者は `calendar_mcp_uid`。

- [ ] **Step 6: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): render per-user settings with mail sending disabled"
```

### Task 5: container コンポーネント

**Files:**
- Create: `roles/calendar_mcp/tasks/container.yml`、`roles/calendar_mcp/templates/compose.yaml.j2`、`roles/calendar_mcp/handlers/main.yml`
- Modify: `roles/calendar_mcp/tasks/main.yml`
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: `__calendar_mcp_image`、`calendar_mcp_users`、`calendar_mcp_uid`、Task 4 のファイル
- Produces: サービス `calendar-mcp-<名前>`。handler `Recreate calendar-mcp`、`Reload Apache`、`Restart fail2ban`（後ろ二つは mailboxd と同じ本体）

- [ ] **Step 1: 失敗するテストを書く**

```python
class CalendarMcpComposeTest(unittest.TestCase):
    def services(self):
        text = render("compose.yaml.j2", __calendar_mcp_image="calendar-mcp:1.9.0-abc1234-12345678")
        return yaml.safe_load(text)["services"]

    def test_one_service_per_user_on_loopback(self):
        s = self.services()
        self.assertEqual(sorted(s), ["calendar-mcp-ts", "calendar-mcp-ubiqu"])
        self.assertEqual(s["calendar-mcp-ts"]["ports"], ["127.0.0.1:8084:8080"])
        self.assertEqual(s["calendar-mcp-ubiqu"]["ports"], ["127.0.0.1:8085:8080"])

    def test_each_service_sees_only_its_own_files(self):
        for name, svc in self.services().items():
            user = name.removeprefix("calendar-mcp-")
            self.assertEqual(svc["env_file"], [{"path": f"{user}.env", "format": "raw"}])
            self.assertIn(f"/srv/calendar_mcp/{user}:/app/data", svc["volumes"])
            self.assertIn(f"/etc/compose/calendar_mcp/{user}/appsettings.json:/app/data/appsettings.json:ro",
                          svc["volumes"])

    def test_hardening(self):
        for svc in self.services().values():
            self.assertEqual(svc["cap_drop"], ["ALL"])
            self.assertIs(svc["read_only"], True)
            self.assertIn("no-new-privileges:true", svc["security_opt"])

    def test_recreate_handler_waits(self):
        handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
        recreate = next(h for h in handlers if h["name"] == "Recreate calendar-mcp")
        module = recreate["community.docker.docker_compose_v2"]
        self.assertEqual(module["recreate"], "always")
        self.assertIs(module["wait"], True)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: 新しいテストが FAIL

- [ ] **Step 3: 実装する**

mailboxd の `compose.yaml.j2` と `container.yml` を手本にする。`environment` に `CALENDAR_MCP_CONFIG: /app/data`、`pull: never`（ローカルのイメージ）。`/srv/calendar_mcp/<名前>` は `calendar_mcp_uid` の `"0750"` で作る。`aspnet:10.0` には `curl` がないので、compose の healthcheck は書かない。代わりに `container | Wait for health` で `ansible.builtin.uri` が一人ずつ `http://127.0.0.1:<port>/health` の 200 を `retries: 24`、`delay: 5` で待つ（check mode では飛ばす）。.NET が `/app/data` と `/tmp` の外に書こうとして起動に失敗したら、その場所を tmpfs に足す。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): run one hardened container per user"
```

### Task 6: apache と fail2ban コンポーネント、playbook

**Files:**
- Create: `roles/calendar_mcp/tasks/apache.yml`、`roles/calendar_mcp/tasks/fail2ban.yml`、`roles/calendar_mcp/templates/calendar-mcp.rewse.jp.conf.j2`、`roles/calendar_mcp/templates/fail2ban-filter.conf.j2`、`roles/calendar_mcp/templates/fail2ban-jail.conf.j2`
- Modify: `roles/calendar_mcp/tasks/main.yml`（import の順は source、config、container、apache、fail2ban）、`home-primary.yml`（services の段にアルファベット順で）、`tests/test_fail2ban_apache.py`（一覧に `calendar_mcp`）
- Test: `tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: `calendar_mcp_hostname`、`calendar_mcp_users`、`networks`
- Produces: ジェイルとフィルタ `calendar_mcp`

- [ ] **Step 1: 失敗するテストを書く**

vhost は利用者ごとに `ProxyPassMatch "^/mcp/<名前>$" "http://127.0.0.1:<port>/" flushpackets=on` と `ProxyPassMatch "^/health/<名前>$" "http://127.0.0.1:<port>/health"` を置く。`<LocationMatch "^/(?!(mcp|health)/(ts|ubiqu)$)">` に `Require all denied`、`<LocationMatch "^/health/">` に zabbix_mcp と同じ並びの `Require ip` を置く。テストは描画した vhost から正規表現を取り出し、Python の `re` で当てる。

```python
class CalendarMcpVhostTest(unittest.TestCase):
    def test_only_exact_mcp_paths_are_open(self):
        deny = denied_pattern(render("calendar-mcp.rewse.jp.conf.j2", networks=NETWORKS))
        for path in ("/mcp/ts", "/mcp/ubiqu"):
            self.assertIsNone(re.search(deny, path), path)
        for path in ("/", "/mcp", "/mcp/ts/", "/mcp/ts/admin", "/mcp/ts/admin/ui",
                     "/mcp/ts/attachments", "/mcp/ts/sse", "/mcp/kyn", "/admin", "/health"):
            self.assertIsNotNone(re.search(deny, path), path)

    def test_each_path_reaches_its_own_port(self):
        text = render("calendar-mcp.rewse.jp.conf.j2", networks=NETWORKS)
        self.assertIn('ProxyPassMatch "^/mcp/ts$" "http://127.0.0.1:8084/" flushpackets=on', text)
        self.assertIn('ProxyPassMatch "^/mcp/ubiqu$" "http://127.0.0.1:8085/" flushpackets=on', text)

    def test_health_is_limited_to_known_networks(self):
        block = location_block(render("calendar-mcp.rewse.jp.conf.j2", networks=NETWORKS), "^/health/")
        self.assertIn("Require ip " + NETWORKS["home_private_ipv4"], block)
        self.assertNotIn("Require all granted", block)

class CalendarMcpFail2banTest(unittest.TestCase):
    def test_filter_counts_401_on_mcp_paths(self):
        regex = failregex()  # rendered, <HOST> replaced as in test_mailboxd.py
        hit = 'calendar-mcp.rewse.jp:443 203.0.113.9 - - [] "POST /mcp/ts HTTP/1.1" 401 0'
        self.assertRegex(hit, regex)
        for miss in (
            hit.replace("401", "200"),
            hit.replace("/mcp/ts", "/.well-known/oauth-protected-resource"),
            hit.replace("calendar-mcp.rewse.jp", "mail-mcp.rewse.jp"),
        ):
            self.assertNotRegex(miss, regex)
```

ログの行の形は mailboxd のフィルタとテストに合わせる。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py tests/test_fail2ban_apache.py -v`
Expected: 新しいテストと `test_every_http_jail_bans_in_apache_and_at_the_firewall` が FAIL

- [ ] **Step 3: 実装する**

mailboxd の `apache.yml`、`fail2ban.yml`、フィルタ、ジェイルを手本にし、名前を `calendar_mcp` と `calendar_mcp_hostname` に替える。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: どちらも通る

- [ ] **Step 5: Commit**

```bash
git add roles/calendar_mcp home-primary.yml tests
git commit -m "feat(calendar_mcp): publish the two MCP paths behind Apache and fail2ban"
```

### Task 7: 1Password と fox への適用（設計の段階 2）

利用者とのやり取りが要る。

**Files:**
- Modify: `roles/calendar_mcp/vars/main.yml`（`apple_item` と `token_item`）

- [ ] **Step 1: 1Password の項目を作る**

利用者に、ts と ubiqu の Apple ID で appleid.apple.com から App 用パスワード（ラベル `calendar-mcp`）を発行してもらう。`ansible` vault に次の項目を `env -u OP_SERVICE_ACCOUNT_TOKEN op item create` で作る。値は端末に出さない。

- `Apple Account - calendar-mcp (ts)` と `(ubiqu)`: `username`（Apple ID）と `password`（App 用パスワード）。App 用パスワードは利用者に 1Password へ直接入れてもらう
- `calendar-mcp - ts` と `calendar-mcp - ubiqu`: `credential` と `admin token`（どちらも `openssl rand -hex 32`）

項目 ID を `vars/main.yml` に書き、`direnv exec . op read op://ansible/<id>/<field> >/dev/null` で八つのフィールドすべてが読めることを確かめる。

- [ ] **Step 2: check mode を流す**

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp --check --diff`
Expected: 失敗なし。ビルドと起動を check mode で飛ばした旨の debug が出る

- [ ] **Step 3: 適用する**

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`
Expected: 成功。二回目は `changed=0`

- [ ] **Step 4: 家から確かめる**

トークンは `op read` からパイプで渡し、表示しない。

- `https://calendar-mcp.rewse.jp/health/ts` が 200
- トークンなしの `POST /mcp/ts` が 401 で、fail2ban のフィルタが行に一致する（`fail2ban-regex`）
- `/mcp/ts/`、`/mcp/ts/admin`、`/mcp/ts/admin/ui`、`/mcp/ts/attachments` が 403
- ts のトークンで `initialize` と `tools/list`。`save_draft` があり、`list_accounts` が `ts-sakura` と `ts-icloud` だけを返す
- ts のトークンで `/mcp/ubiqu` が 401。`accountId: ubiqu-sakura` は拒否される
- `send_email`（宛先は ts 自身）と `unsubscribe_from_email` が権限エラーになる
- `docker logs calendar-mcp-ts` で、ツールの呼び出しがどこまで記録されるかを見る。設計の「残るリスク」に関わるので、結果を利用者に報告する

- [ ] **Step 5: Commit**

```bash
git add roles/calendar_mcp/vars/main.yml
git commit -m "feat(calendar_mcp): reference the 1Password items"
```

### Task 8: Quick Tunnel で Muse から確かめる（設計の段階 3）

利用者とのやり取りが要る。コミットはない。

- [ ] **Step 1: トンネルを起動する**

fox で `cloudflared tunnel --url http://127.0.0.1:8084` を手で起動し、`*.trycloudflare.com` の名前を読む。

- [ ] **Step 2: Muse で試してもらう**

設計の付録のプロンプトに名前を入れて利用者に渡す。トークンは `calendar-mcp - ts` の `credential`。結果を受け取り、`docker logs calendar-mcp-ts`、Sakura の Drafts フォルダー（`\Draft` 付きで日本語が化けていない）、送信済みフォルダー（何も増えていない）で裏付ける。

- [ ] **Step 3: トンネルを止める**

`pgrep cloudflared` が何も返さないことで確かめる。

### Task 9: CloudFront、UniFi、security-agent（設計の段階 4）

AGENTS.md の「Subdomains」に従う。各リポジトリでは `git pull` してから作業する。

- [ ] **Step 1: cloudfront-waf**

`calendar-mcp.rewse.jp` を `Aliases`、`SUBDOMAINS`、テスト、`README.md`、`docs/setup.md` の名前の一覧と数に足し、テストを通してコミット、push する。`AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` と `AWS_PROFILE=cloudfront-waf-deploy scripts/switch-dns.sh cloudfront` を流す。

- [ ] **Step 2: UniFi**

`calendar-mcp.rewse.jp` を `fox.rewse.jp` に向ける CNAME の DNS ポリシーを `ttlSeconds: 0` で足す。

- [ ] **Step 3: security-agent**

`targets.toml` と `infra/template.yaml` に `calendar-mcp.rewse.jp` を足す。日は 26 日とし、mailboxd の `cron(15 21 26 * ? *)` と重ならないよう `cron(45 21 26 * ? *)` にする。対象ドメインを先に作って検証してから（`AWS_PROFILE=security-agent-deploy`）、テストのスケジュールを入れる。コミット、push する。

- [ ] **Step 4: 本番の経路で確かめる**

利用者に Muse のコネクタの URL を `https://calendar-mcp.rewse.jp/mcp/ts` に替えてもらい、付録の 1、5、8、10 をもう一度試してもらう。WAF のログで Muse の通信がブロックされていないこと、INBOX の条件なしの一覧と今週の予定が 60 秒以内に返ることを見る。

### Task 10: ubiqu のコネクタ（設計の段階 5）

利用者とのやり取りが要る。コミットはない。

- [ ] **Step 1: プロンプトを渡す**

付録のプロンプトの URL を `https://calendar-mcp.rewse.jp/mcp/ubiqu` にしたものを利用者に渡す。トークンは `calendar-mcp - ubiqu` の `credential`。

- [ ] **Step 2: 確かめる**

`docker logs calendar-mcp-ubiqu` で呼び出しを確かめ、利用者の結果で `list_accounts` に ts のアカウントが出ないことを確かめる。

### Task 11: mailboxd の撤去（設計の段階 6）

**Files:**
- Create: `roles/calendar_mcp/tasks/legacy.yml`（mailboxd の後始末。全ホストで済んだら次の変更で消す）
- Modify: `roles/calendar_mcp/tasks/main.yml`、`home-primary.yml`（`mailboxd` を外す）、`tests/test_fail2ban_apache.py`（`mailboxd` を外す）、`tests/test_calendar_mcp.py`
- Delete: `roles/mailboxd/`、`tests/test_mailboxd.py`

- [ ] **Step 1: 利用者に確かめる**

二人とも新しいコネクタで使えていること、Muse の古いコネクタを消してよいこと、1Password の mailboxd のトークン三つ（`7tbut3qmtfp7dettl6hqsh6tei`、`pjplhxwrdrm25hob63i37iqdkm`、`b7wlevkrmcvdmd5x27wdzfgewu`）を消してよいことを確かめる。

- [ ] **Step 2: 失敗するテストを書く**

```python
class CalendarMcpLegacyTest(unittest.TestCase):
    def test_removes_only_mailboxd_state(self):
        tasks = yaml.safe_load((ROLE / "tasks" / "legacy.yml").read_text())
        paths = sorted(t["ansible.builtin.file"]["path"] for t in tasks if "ansible.builtin.file" in t)
        self.assertEqual(paths, [
            "/etc/apache2/sites-available/mail-mcp.rewse.jp.conf",
            "/etc/compose/mailboxd",
            "/etc/fail2ban/filter.d/mailboxd.conf",
            "/etc/fail2ban/jail.d/mailboxd.conf",
            "/srv/mailboxd",
        ])
        for t in tasks:
            if "ansible.builtin.file" in t:
                self.assertEqual(t["ansible.builtin.file"]["state"], "absent")
```

- [ ] **Step 3: 実装する**

`legacy.yml` の順は、`/etc/compose/mailboxd/compose.yaml` の `stat`、あれば `community.docker.docker_compose_v2` の `state: absent`、`a2dissite mail-mcp.rewse.jp`（`changed_when` を出力で判定、有効なときだけ）、上のファイルとディレクトリの `state: absent`。`Reload Apache` と `Restart fail2ban` を通知する。`main.yml` の最後に `calendar_mcp_legacy` のタグで import する。`roles/mailboxd/` と `tests/test_mailboxd.py` を `git rm` し、`home-primary.yml` と `tests/test_fail2ban_apache.py` から外す。

- [ ] **Step 4: テストと lint**

Run: `uv run --with pytest --with ansible-core pytest tests -q` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: どちらも通る。`rg -n 'mailboxd|mail-mcp' --glob '!docs/**'` が `legacy.yml` とそのテストだけを返す

- [ ] **Step 5: 適用して確かめる**

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`
Expected: 成功。fox に `mailboxd` のコンテナ、`/srv/mailboxd`、`/etc/compose/mailboxd`、vhost がなく、`fail2ban-client status` に `mailboxd` がない。二回目は `changed=0`

- [ ] **Step 6: Commit**

```bash
git add -A roles tests home-primary.yml
git commit -m "feat(mailboxd)!: retire mailboxd in favor of calendar_mcp"
```

- [ ] **Step 7: 他のリポジトリと 1Password を片づける**

cloudfront-waf から `mail-mcp.rewse.jp` を外してデプロイと DNS の切り替え、UniFi の `mail-mcp.rewse.jp` のポリシーを削除、security-agent から `mail-mcp.rewse.jp` のテストと対象ドメインを外す。`https://mail-mcp.rewse.jp/` に届かないことを確かめる。1Password の mailboxd のトークン三つを、Step 1 の確認のとおり消す。

- [ ] **Step 8: マージ**

ブランチ全体のレビューのあと、`main` にマージする。マージのコミットで、mailboxd の設計と計画（`2026-11-02-mailboxd-mcp-design.md`、`2026-11-02-mailboxd-mcp.md`）とこの設計と計画を `git mv` で `docs/superpowers/archive/specs/` と `docs/superpowers/archive/plans/` に移す。

### Task 12: fork に三つの変更をテスト付きで積む

`~/git/calendar-mcp`（fork の clone）で行う。三つの変更は、`/tmp/calmcp-patch.*` の作業ツリーと `roles/calendar_mcp/files/calendar-mcp.patch` にある実装を参考にしてよいが、テストを先に書いてアサーションで落ちるのを確かめてから実装を入れる。コンパイルエラーは RED とみなさない。テストが参照する型やメソッドは、先に中身のない形（`throw new NotImplementedException()` や空の戻り値）で足してコンパイルを通す。

**Files（fork の中）:**
- Modify: `.github/workflows/ci.yml`（`push.branches` と `pull_request.branches` に `rewse`）
- Modify: `src/CalendarMcp.Core/Providers/ImapProviderService.cs`、`src/CalendarMcp.Core/Services/IProviderService.cs`、`src/CalendarMcp.Core/Models/EmailMessage.cs`、`src/CalendarMcp.Core/Tools/GetEmailDetailsTool.cs`、`src/CalendarMcp.HttpServer/Program.cs`、`src/CalendarMcp.StdioServer/Program.cs`（ツールの登録は両方のサーバーに）、`docs/IMAP-SETUP.md`（`draftsFolder`）
- Create: `src/CalendarMcp.Core/Tools/SaveDraftTool.cs`、`changelogs/2026-11-07-imap-drafts-folder.md`、`changelogs/2026-11-07-save-draft-tool.md`、`changelogs/2026-11-07-email-headers.md`
- Test: `src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`、`src/CalendarMcp.Tests/Tools/SaveDraftToolTests.cs`（新規）、`src/CalendarMcp.Tests/Tools/GetEmailDetailsToolTests.cs`、`src/CalendarMcp.Tests/Tools/PermissionEnforcementTests.cs`

**Interfaces:**
- Produces: fork `rewse/calendar-mcp` の既定ブランチ `rewse`。上流の `6486836`（Release 1.9.0）の上に、CI のコミットと三つの変更のコミットがこの順で載る
- Produces: Task 2 の Interfaces と同じ `save_draft`、`IProviderService.SaveDraftAsync`、`ImapProviderService.BuildDraftMessage`。加えて `ImapAccountConfig.DraftsFolder`（`string?`、既定 null）、`internal static List<EmailHeader> ImapProviderService.ToEmailHeaders(HeaderList)`、`EmailMessage.Headers`（`List<EmailHeader>?`）、`public sealed record EmailHeader(string Name, string Value)`、`get_email_details` の応答の `headers`（`[{name, value}]`、ヘッダーを持たないプロバイダーでは null）

- [ ] **Step 1: fork と clone**

Run: `gh repo fork MarimerLLC/calendar-mcp --clone=false && git clone https://github.com/rewse/calendar-mcp.git ~/git/calendar-mcp && cd ~/git/calendar-mcp && git remote add upstream https://github.com/MarimerLLC/calendar-mcp.git && git switch -c rewse 6486836`
Expected: `git -P log --oneline -1` が `6486836 Release 1.9.0 (#115)`

- [ ] **Step 2: CI の対象ブランチ**

`ci.yml` の二つの `branches` に `rewse` を足して commit する（`ci: run CI on the rewse branch`）。fork の Actions を有効にし、`gh workflow disable release.yml -R rewse/calendar-mcp` と `gh workflow disable claude.yml -R rewse/calendar-mcp` で二つを止める。

- [ ] **Step 3: 下書きフォルダーの設定（RED）**

`ImapProviderServiceTests` に `ResolveConfiguredFolder_MapsDraftsToConfiguredFolder`（`CustomFolders with { DraftsFolder = "INBOX.Draft" }` で `drafts` が `"INBOX.Draft"`）を書く。`ImapAccountConfig` に `string? DraftsFolder = null` だけを足してコンパイルを通す。
Run: `container run --rm -m 6G -c 4 -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:10.0 dotnet test src/CalendarMcp.Tests --filter ResolveConfiguredFolder`
Expected: `MapsDraftsToConfiguredFolder` が `Assert.AreEqual failed. Expected:<INBOX.Draft>. Actual:<(null)>` で FAIL、ほかは PASS

- [ ] **Step 4: 下書きフォルダーの設定（GREEN）と commit**

`ResolveConfiguredFolder` の `Drafts` と `ResolveConfigAsync` の `draftsFolder` を足し、`docs/IMAP-SETUP.md` の設定の表と changelog を書く。全テストを通して commit する（`Add an optional draftsFolder for IMAP accounts`）。`ResolveConfigAsync` は上流にも単体テストがなく、`sentFolder` なども同じなので、`draftsFolder` の読み取りは Task 13 の実機の確認で押さえる。

- [ ] **Step 5: 下書きの保存（RED）**

`SaveDraftToolTests` に次を書く。`SaveDraftTool` は引数を受けて `throw new NotImplementedException()` するだけの形、`IProviderService.SaveDraftAsync` は既定の実装付きの宣言、`BuildDraftMessage` は `new MimeMessage()` を返すだけの形で先に足す。

```csharp
SaveDraft_EmptyAccountId_ThrowsMcpException          // "accountId is required"
SaveDraft_NoRecipients_ThrowsMcpException            // to = [] → "At least one recipient is required in 'to'."
SaveDraft_AccountWithoutEmailRead_IsRefused          // Scoped(..., CalendarRead) → McpException, provider not called
SaveDraft_EmailReadOnly_SavesWithoutSendPermission   // Scoped(..., EmailRead): provider.SaveDraftAsync("acc-1", "a@example.com, b@example.com", "s", "b", "text", null, "INBOX/1/2", ...) once; JSON success=true, draftEmailId="INBOX.Draft/9/3"
```

`ImapProviderServiceTests` に Task 2 の `BuildDraftMessage_SetsHeadersAndUtf8Body` と `BuildDraftMessage_ThreadsAReply` を書く。`PermissionEnforcementTests` に、`emailRead` のない IMAP アカウントで `save_draft` が拒否されるテストを、既存の `move_email` の形に合わせて足す。
Run: `... dotnet test src/CalendarMcp.Tests --filter "SaveDraft|BuildDraftMessage|PermissionEnforcement"`
Expected: 新しいテストが `NotImplementedException` かアサーションで FAIL

- [ ] **Step 6: 下書きの保存（GREEN）と commit**

Task 2 Step 4 の内容で実装し、二つのサーバーの `Program.cs` に登録して changelog を書く。全テストを通して commit する（`Add a save_draft tool for IMAP accounts`）。IMAP の APPEND とフラグは上流にも IMAP サーバーのモックがないので、Task 13 の実機の確認で押さえる。

- [ ] **Step 7: ヘッダー（RED）**

`ImapProviderServiceTests` に `ToEmailHeaders_KeepsEveryFieldInOrder`（Received が二つ、`ARC-Authentication-Results` が一つ、順番と値が保たれる）、`GetEmailDetailsToolTests` に `GetEmailDetails_ReturnsHeadersWhenProviderHasThem`（応答の `headers[0].name` と `value`）と `GetEmailDetails_HeadersNullWhenProviderHasNone` を書く。`EmailHeader` と `EmailMessage.Headers` を宣言し、`ToEmailHeaders` は空のリストを返す形で先に足す。
Run: `... dotnet test src/CalendarMcp.Tests --filter "ToEmailHeaders|GetEmailDetails"`
Expected: 新しい三つのうち、`ToEmailHeaders` と `ReturnsHeaders` がアサーションで FAIL

- [ ] **Step 8: ヘッダー（GREEN）と commit**

IMAP の詳細の組み立てで `Headers = ToEmailHeaders(m.Headers)` を設定し、ツールの応答に `headers` を足して、ツールの説明文と changelog を直す。全テストを通して commit する（`Return email headers from get_email_details`）。

- [ ] **Step 9: push と CI**

Run: `git push -u origin rewse && gh repo edit rewse/calendar-mcp --default-branch rewse && gh run watch -R rewse/calendar-mcp --exit-status $(gh run list -R rewse/calendar-mcp -b rewse -L 1 --json databaseId -q '.[0].databaseId')`
Expected: CI Build が成功

### Task 13: ロールを fork からのビルドに切り替える

**Files:**
- Modify: `roles/calendar_mcp/tasks/container.yml`、`tests/test_calendar_mcp.py`
- Delete: `roles/calendar_mcp/files/calendar-mcp.patch`

**Interfaces:**
- Consumes: Task 12 の `rewse/calendar-mcp` の既定ブランチ
- Produces: `__calendar_mcp_image` は `calendar-mcp:<commit の先頭 12 文字>`

- [ ] **Step 1: 失敗するテストを書く**

`CalendarMcpBuildTest` を次に置き換える。

```python
def test_lookup_follows_the_fork_without_cooldown(self):
    fact = task_named("container.yml", "container | Resolve fork commit")["ansible.builtin.set_fact"]["__calendar_mcp_source"]
    self.assertIn("github-commit:rewse/calendar-mcp", fact)
    self.assertIn("days=0", fact)

def test_image_tag_is_the_commit(self):
    fact = task_named("container.yml", "container | Name image")["ansible.builtin.set_fact"]["__calendar_mcp_image"]
    self.assertIn("__calendar_mcp_source.commit[:12]", fact)

def test_checkout_is_the_fork(self):
    git = task_named("container.yml", "container | Check out repository")["ansible.builtin.git"]
    self.assertEqual(git["repo"], "https://github.com/rewse/calendar-mcp.git")

def test_no_patch_is_applied(self):
    self.assertNotIn("ansible.posix.patch", (ROLE / "tasks" / "container.yml").read_text())
    self.assertFalse((ROLE / "files" / "calendar-mcp.patch").exists())
```

`test_build_is_skipped_when_the_image_exists` は「Apply patch」を外して残す。`test_checkout_starts_clean` は消す（パッチがなければ forced checkout で足りる）。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: 新しい四つが FAIL

- [ ] **Step 3: 実装する**

`container.yml` の lookup を `lookup('aged_release', 'github-commit:rewse/calendar-mcp', days=0)` に、名前を `container | Resolve fork commit` に、タグを `'calendar-mcp:' ~ __calendar_mcp_source.commit[:12]` に、checkout を fork の URL と `force: true` にする。`Remove previous checkout` と `Apply patch` を消し、パッチのファイルを `git rm` する。コメントは、fork を自分のリポジトリとして待機期間なしで追い、上流の待機期間は rebase の元で守ることを書く。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q` と pre-commit
Expected: どちらも通る

- [ ] **Step 5: Commit、適用、確認**

```bash
git add -A roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): build from the rewse fork instead of a patch"
```

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`
Expected: 成功し、二回目は `changed=0`。Task 7 Step 4 の確認（`/tmp/calmcp-verify/mcp.py`）をもう一度通し、加えて `get_email_details` が `ARC-Authentication-Results` を含む `headers` を返す。`save_draft` で自分宛ての下書きを一つ保存し、Sakura の `INBOX.Draft` に `\Draft` 付きで入り、`INBOX.Sent` に何も増えないことを IMAP で確かめてから、その下書きを消す
