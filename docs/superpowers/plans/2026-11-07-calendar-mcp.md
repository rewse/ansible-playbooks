# calendar-mcp 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox で MarimerLLC/calendar-mcp を ts と ubiqu の一人一つずつ動かし、Muse から iCloud のカレンダーと連絡先、Sakura のメールを使えるようにする。メールは下書きまでで、送信と配信停止はできない。最後に mailboxd を撤去する。

**Architecture:** 上流を `rewse/calendar-mcp` に fork し、待機期間を過ぎた上流の Release の上に四つの変更をテスト付きで積む。`aged_release` で fork の既定ブランチの最新のコミットを選び、fox で checkout とビルドを行う。新しいロール `calendar_mcp` が Compose で二つのコンテナを `127.0.0.1:8084` と `127.0.0.1:8085` に立て、Apache の vhost `calendar-mcp.rewse.jp` が `/mcp/ts` と `/mcp/ubiqu` だけを流す。Quick Tunnel で Muse から確かめてから、CloudFront、UniFi の DNS、security-agent を入れる。

**Tech Stack:** Ansible（community.docker）、Docker Compose、.NET 10（上流）、MSTest と Rocks（fork のテスト）、Apache、fail2ban、1Password CLI、pytest と unittest + jinja2

**Spec:** `docs/superpowers/specs/2026-11-07-calendar-mcp-design.md`

**改訂（2026-11-07）:** 設計を fork 方式に改めた。Task 2 と Task 3 は実施済みの記録として残すが、そのパッチの作成と適用は、Task 12 から 15（fork と三つの変更をテスト付きで積む）と Task 16（ロールを fork からのビルドに切り替える）で置き換える。Task 12 から 16 は Task 8 より前に行う。

**改訂（2026-11-07、二回目）:** ヘッダーは `get_email_details` に足さず、新しいツール `get_email_headers` で返す設計に改めた。Task 15 は実施済みの記録として残し、そのコミット fbc6950 は fork で 30936fe として revert した。代わりに Task 17 を行う。Task 16 は Step 5 まで実施済みで、Step 6 と Step 7 は Task 17 の push のあとに行う。順番は Task 17、Task 16 の Step 6 と Step 7、Task 8 となる。

**改訂（2026-11-07、三回目）:** Task 8 で、Sakura の IMAP では `get_emails` が頼んだ件数より少なく返ることが分かった（設計の「UID の並び」）。Task 18 で直す。Task 8 は Step 1 から 3 まで実施済みで、一覧のほかはすべて通った。Task 18 の Step 8 が通ったら Task 8 を完了とする。Muse からの一覧の確かめ直しは、Task 9 で CloudFront 経由の段階 3 を確かめるときに行う。

**改訂（2026-11-07、四回目）:** Task 10 は利用者の判断で飛ばした。最終レビューで、.NET のベースイメージが固定も更新もされないこと（設計の「イメージのビルド」）と、iCloud がカレンダーの書き込みを受けて招待のメールを送ること（設計の「招待の制限」）が分かった。Task 19 と Task 20 で直す。利用者の求めで、fork の変更ごとに `README.md`、`docs/`、`Skills/` の文書も直す（設計の「文書」）。すでに積んだ二つの文書は Task 21 で足す。そのあとで Task 11 の Step 8（マージ）を行う。

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
- fork の既定ブランチに新しいコミットを push したとき。次の `update` でイメージを作り直し、同じコミットなら作り直さないこと（Task 16 のテスト、タグにコミット SHA を入れる）
- Muse がメールのツール `get_email_headers` に iCloud のアカウント（`ts-icloud`）を渡す。DAV はメールを扱わないので、空のヘッダーを返さず `Failed to get email headers: This account does not support this operation.` で拒否されること（Task 17 のテスト）
- `save_draft` を `emailRead` のないアカウントで呼ぶ。プロバイダーを呼ばずに拒否されること（Task 14 のテスト）

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

### Task 2: 下書きのパッチ（Task 13 から 15 で置き換え）

> 実施済み。fork 方式への改訂で、ここで作るパッチは Task 16 で削除し、同じ変更を Task 13 から 15 で fork にテスト付きで積み直す。新しく実行しない。

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

### Task 3: source コンポーネント（Task 16 で置き換え）

> 実施済み。Task 5 で container コンポーネントに統合し、パッチの適用は Task 16 で fork からのビルドに置き換える。新しく実行しない。

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

### Task 12: fork と CI

**Files（fork の中）:**
- Modify: `.github/workflows/ci.yml`（`on.push.branches` と `on.pull_request.branches`）

**Interfaces:**
- Produces: fork `rewse/calendar-mcp`、その clone `~/git/calendar-mcp`（remote `origin` が fork、`upstream` が MarimerLLC）、既定ブランチ `rewse`（上流の `6486836` Release 1.9.0 の上に CI のコミット一つ）。Task 13 から 15 はこのブランチに積む

- [ ] **Step 1: fork する**

Run: `gh repo fork MarimerLLC/calendar-mcp --clone=false`
Expected: `gh repo view rewse/calendar-mcp --json parent -q .parent.nameWithOwner` が `MarimerLLC/calendar-mcp`

- [ ] **Step 2: clone してブランチを作る**

Run: `git clone -q https://github.com/rewse/calendar-mcp.git ~/git/calendar-mcp && git -C ~/git/calendar-mcp remote add upstream https://github.com/MarimerLLC/calendar-mcp.git && git -C ~/git/calendar-mcp switch -c rewse 6486836`
Expected: `git -C ~/git/calendar-mcp -P log --oneline -1` が `6486836 Release 1.9.0 (#115)`

- [ ] **Step 3: CI の対象に `rewse` を足す**

`.github/workflows/ci.yml` の `on.push.branches` と `on.pull_request.branches` を `[main, rewse]` にする。ほかの行は変えない（上流に送らない fork だけのコミットなので、差分を小さく保つ）。

- [ ] **Step 4: Commit と push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run CI on the rewse branch"
git push -u origin rewse
```

- [ ] **Step 5: 既定ブランチと Actions を設定する**

Run: `gh repo edit rewse/calendar-mcp --default-branch rewse && gh api -X PUT repos/rewse/calendar-mcp/actions/permissions -F enabled=true -f allowed_actions=all && gh workflow disable release.yml -R rewse/calendar-mcp && gh workflow disable claude.yml -R rewse/calendar-mcp`
Expected: `gh workflow list -R rewse/calendar-mcp --all` で `Build and Release` と `Claude Code` が `disabled_manually`、`CI Build` が `active`

- [ ] **Step 6: CI が通ることを確かめる**

Run: `gh workflow run ci.yml -R rewse/calendar-mcp --ref rewse && sleep 10 && gh run watch -R rewse/calendar-mcp --exit-status "$(gh run list -R rewse/calendar-mcp -w ci.yml -b rewse -L 1 --json databaseId -q '.[0].databaseId')"`
Expected: 成功。`ci.yml` に `workflow_dispatch` がなく `workflow run` が拒まれたら、Step 4 の push で起きた run を `gh run list` で探して待つ

### Task 13: IMAP の `draftsFolder`

以下、fork の Task はすべて `~/git/calendar-mcp` の `rewse` ブランチで行う。.NET の SDK は Mac の `dotnet`（10.0、darwin ロールで入れている）を使う。

**Files:**
- Modify: `src/CalendarMcp.Core/Providers/ImapProviderService.cs`（`ImapAccountConfig`、`ResolveConfigAsync`、`ResolveConfiguredFolder`）
- Modify: `docs/IMAP-SETUP.md`（設定の表に `draftsFolder`）
- Create: `changelogs/2026-11-07-imap-drafts-folder.md`（`changelogs/2026-09-23-move-email-folder-aliases.md` と同じ見出しの形）
- Test: `src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`

**Interfaces:**
- Produces: `ImapAccountConfig` の末尾の引数 `string? DraftsFolder = null`。`providerConfig` の `draftsFolder`（任意、既定なし）から読む
- Produces: `ResolveConfiguredFolder(WellKnownMailFolder.Drafts, cfg)` が `cfg.DraftsFolder` を返す。null なら今までどおり SPECIAL-USE に落ちる

- [ ] **Step 1: 失敗するテストを書く**

```csharp
[TestMethod]
public void ResolveConfiguredFolder_MapsDraftsToConfiguredFolder()
{
    Assert.IsTrue(MailFolderAliases.TryParse("drafts", out var folder));

    Assert.AreEqual("INBOX.Draft", ImapProviderService.ResolveConfiguredFolder(
        folder, CustomFolders with { DraftsFolder = "INBOX.Draft" }));
}
```

既存の `ResolveConfiguredFolder_ReturnsNullForSpecialUseOnlyAliases`（`archive` と `drafts`）は、`CustomFolders` が `DraftsFolder` を持たないので変えずに通る。そのコメントの「No providerConfig key for these」は「No providerConfig key for archive, and none set here for drafts」に直す。

- [ ] **Step 2: コンパイルだけ通す**

`ImapAccountConfig` の末尾に `string? DraftsFolder = null` を足す。ほかは変えない。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter ResolveConfiguredFolder`
Expected: `ResolveConfiguredFolder_MapsDraftsToConfiguredFolder` だけが `Assert.AreEqual failed. Expected:<INBOX.Draft>. Actual:<(null)>` で FAIL

- [ ] **Step 4: 実装する**

`ResolveConfiguredFolder` に `WellKnownMailFolder.Drafts => cfg.DraftsFolder` を足し、`ResolveConfigAsync` で `draftsFolder` が空でなければ渡す（空なら null）。`docs/IMAP-SETUP.md` の表と changelog に、SPECIAL-USE を広告しないサーバー（例として `INBOX.Draft` を使うもの）のための設定であることを書く。`ResolveConfigAsync` の読み取りは、`sentFolder` などと同じく上流に単体テストがないので、Task 16 の実機で確かめる。

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests`
Expected: `Failed: 0`

- [ ] **Step 6: Commit**

```bash
git add src/CalendarMcp.Core/Providers/ImapProviderService.cs src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs docs/IMAP-SETUP.md changelogs/2026-11-07-imap-drafts-folder.md
git commit -m "Add an optional draftsFolder for IMAP accounts"
```

### Task 14: `save_draft`

**Files:**
- Create: `src/CalendarMcp.Core/Tools/SaveDraftTool.cs`、`changelogs/2026-11-07-save-draft-tool.md`
- Modify: `src/CalendarMcp.Core/Services/IProviderService.cs`（CRLF のまま）、`src/CalendarMcp.Core/Providers/ImapProviderService.cs`、`src/CalendarMcp.HttpServer/Program.cs`、`src/CalendarMcp.StdioServer/Program.cs`（どちらも `MoveEmailTool` の次に登録）
- Test: `src/CalendarMcp.Tests/Tools/SaveDraftToolTests.cs`（新規）、`src/CalendarMcp.Tests/Tools/PermissionEnforcementTests.cs`、`src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`

**Interfaces:**
- Consumes: Task 13 の `ImapAccountConfig.DraftsFolder`（`drafts` の解決に使う）
- Produces: `IProviderService.SaveDraftAsync(string accountId, string to, string subject, string body, string bodyFormat = "html", List<string>? cc = null, string? inReplyToEmailId = null, CancellationToken cancellationToken = default)`、返り値 `Task<string?>`（下書きのメール ID、UID が分からなければ null）。既定の実装は `NotSupportedException("This provider does not support saving drafts.")`
- Produces: `public sealed class SaveDraftTool(IAccountRegistry, IProviderServiceFactory, ILogger<SaveDraftTool>)` の `Task<string> SaveDraft(string accountId, List<string> to, string subject, string body = "", string bodyFormat = "html", List<string>? cc = null, string? inReplyToEmailId = null)`。MCP の名前は `save_draft`。応答は `{success, accountId, draftEmailId, message}`
- Produces: `internal static MimeMessage ImapProviderService.BuildDraftMessage(string from, string to, List<string>? cc, string subject, string body, string bodyFormat, string? inReplyToMessageId, IEnumerable<string>? references)`

- [ ] **Step 1: 失敗するテストを書く**

`SaveDraftToolTests.cs`（`MoveEmailToolTests` と同じ using と組み立て。`NewTool()` は空の `IAccountRegistryCreateExpectations` と `IProviderServiceFactoryCreateExpectations` で `SaveDraftTool` を作る補助）:

```csharp
[TestMethod]
public async Task SaveDraft_EmptyAccountId_ThrowsMcpException()
{
    var ex = await Assert.ThrowsExactlyAsync<McpException>(
        () => NewTool().SaveDraft("", ["a@example.com"], "s"));
    Assert.AreEqual("accountId is required", ex.Message);
}

[TestMethod]
public async Task SaveDraft_NoRecipients_ThrowsMcpException()
{
    var ex = await Assert.ThrowsExactlyAsync<McpException>(
        () => NewTool().SaveDraft("acc-1", [], "s"));
    Assert.AreEqual("At least one recipient is required in 'to'.", ex.Message);
}

[TestMethod]
public async Task SaveDraft_Success_PassesArgumentsAndReturnsDraftId()
{
    // regExp: GetAccountAsync("acc-1") → TestData.CreateAccount(id: "acc-1", provider: "imap")
    // provExp.Setups.SaveDraftAsync("acc-1", "a@example.com, b@example.com", "s", "b", "text",
    //     null, "INBOX/1/2", Arg.Any<CancellationToken>()).ReturnValue(Task.FromResult<string?>("INBOX.Draft/9/3"))
    // factExp.Setups.GetProvider("imap").ReturnValue(provExp.Instance())
    var doc = JsonDocument.Parse(await tool.SaveDraft(
        "acc-1", ["a@example.com", "b@example.com"], "s", "b", "text", null, "INBOX/1/2"));
    Assert.IsTrue(doc.RootElement.GetProperty("success").GetBoolean());
    Assert.AreEqual("INBOX.Draft/9/3", doc.RootElement.GetProperty("draftEmailId").GetString());
    regExp.Verify(); factExp.Verify(); provExp.Verify();
}
```

`PermissionEnforcementTests.cs`（`SendEmail_ReadOnlyAccount_Throws` と同じ形）:

```csharp
SaveDraft_AccountWithoutEmailRead_Throws
    // Scoped("cal-only", AccountPermission.CalendarRead, provider: "imap"); provider factory with no setups
    // McpException whose message contains "does not permit reading email"
SaveDraft_ReadOnlyAccount_SavesWithoutSendPermission
    // Scoped("read-only", AccountPermission.EmailRead, provider: "imap"); SaveDraftAsync set up as above
    // returns success=true — saving a draft needs no emailSend
```

`ImapProviderServiceTests.cs`:

```csharp
[TestMethod]
public void BuildDraftMessage_SetsHeadersAndUtf8Body()
{
    var m = ImapProviderService.BuildDraftMessage(
        "me@example.com", "a@example.com, b@example.com", null, "件名テスト", "本文テスト", "text", null, null);
    Assert.AreEqual("me@example.com", m.From.Mailboxes.Single().Address);
    CollectionAssert.AreEqual(new[] { "a@example.com", "b@example.com" },
        m.To.Mailboxes.Select(x => x.Address).ToArray());
    Assert.AreEqual("件名テスト", m.Subject);
    var part = m.Body as MimeKit.TextPart;
    Assert.IsNotNull(part);
    Assert.AreEqual("本文テスト", part.Text);
    Assert.IsTrue(part.IsPlain);
}

[TestMethod]
public void BuildDraftMessage_ThreadsAReply()
{
    var m = ImapProviderService.BuildDraftMessage(
        "me@example.com", "a@example.com", null, "Re: x", "<p>y</p>", "html",
        "orig@example.com", new[] { "root@example.com", "orig@example.com" });
    Assert.AreEqual("orig@example.com", m.InReplyTo);
    CollectionAssert.AreEqual(new[] { "root@example.com", "orig@example.com" }, m.References.ToArray());
    var part = m.Body as MimeKit.TextPart;
    Assert.IsNotNull(part);
    Assert.IsTrue(part.IsHtml);
}
```

- [ ] **Step 2: コンパイルだけ通す**

`IProviderService.SaveDraftAsync` を既定の実装付きで宣言する。`SaveDraftTool` を上の形で作り、`SaveDraft` の本体は `throw new NotImplementedException();` にする。`BuildDraftMessage` は `new MimeMessage()` を返すだけにする。Rocks が `IProviderService` の既定の実装を持つメソッドの `Setups` を作らなければ、そのテストは `IImapProviderService` のモックに替える。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter "SaveDraft|BuildDraftMessage"`
Expected: 新しい七つがすべて FAIL。ツールのテストは `NotImplementedException` が期待した `McpException` でないため、`BuildDraftMessage` のテストはアサーションで落ちる

- [ ] **Step 4: 実装する**

- `SaveDraftTool.SaveDraft`: `MoveEmailTool` と同じ順で `ToolGuard.RequireNonEmpty(accountId)`、宛先の確認、`ToolGuard.RequireAccountAsync(..., AccountPermission.EmailRead)`、プロバイダーの呼び出し。宛先は `string.Join(", ", to)` で渡す。説明文に、下書きを保存するだけで送信しないことと、返信には `inReplyToEmailId` を渡すことを書く
- `ImapProviderService.SaveDraftAsync`: 返信元があれば `ParseEmailId` と `EnsureUidValidity` のうえで `MessageSummaryItems.Envelope | MessageSummaryItems.References` を fetch し、`In-Reply-To` は返信元の Message-Id、`References` は返信元の References に Message-Id を足したものにする。下書きの置き場所は `ResolveFolderAsync(client, cfg, "drafts", ct)`、フラグは `MessageFlags.Draft | MessageFlags.Seen`。ID は APPEND が返す UID と `UidValidity` から `FormatEmailId` で作る
- `BuildDraftMessage`: 差出人は `cfg.Username`、本文は `bodyFormat` が `text` なら plain、それ以外は html の `TextPart`。`SendEmailAsync` の組み立てとは共有しない
- 二つの `Program.cs` に登録し、changelog に `emailRead` で判定する理由（外に何も出さない）を書く

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests && dotnet build src/CalendarMcp.HttpServer -c Release`
Expected: `Failed: 0` と `Build succeeded.`

- [ ] **Step 6: Commit**

```bash
git add src changelogs/2026-11-07-save-draft-tool.md
git commit -m "Add a save_draft tool for IMAP accounts"
```

### Task 15: `get_email_details` のヘッダー（Task 17 で置き換え）

> 実施済み（fbc6950）。ヘッダーは新しいツール `get_email_headers` で返す設計に改め、fbc6950 は 30936fe で revert した。同じ目的を Task 17 で積み直す。新しく実行しない。

**Files:**
- Modify: `src/CalendarMcp.Core/Models/EmailMessage.cs`、`src/CalendarMcp.Core/Providers/ImapProviderService.cs`（詳細の組み立て）、`src/CalendarMcp.Core/Tools/GetEmailDetailsTool.cs`（応答と説明文）
- Create: `changelogs/2026-11-07-email-headers.md`
- Test: `src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`、`src/CalendarMcp.Tests/Tools/GetEmailDetailsToolTests.cs`

**Interfaces:**
- Produces: `public sealed record EmailHeader(string Name, string Value)`、`EmailMessage.Headers`（`List<EmailHeader>?`、既定 null）、`internal static List<EmailHeader> ImapProviderService.ToEmailHeaders(HeaderList headers)`
- Produces: `get_email_details` の応答の `headers`。IMAP では `[{"name": ..., "value": ...}]` をメッセージの順で、ほかのプロバイダーでは null

- [ ] **Step 1: 失敗するテストを書く**

```csharp
// ImapProviderServiceTests
[TestMethod]
public void ToEmailHeaders_KeepsEveryFieldInOrder()
{
    var headers = new MimeKit.HeaderList
    {
        { "Received", "from a" },
        { "Received", "from b" },
        { "ARC-Authentication-Results", "i=1; rewse.jp; spf=pass" },
    };
    var result = ImapProviderService.ToEmailHeaders(headers);
    CollectionAssert.AreEqual(new[] { "Received", "Received", "ARC-Authentication-Results" },
        result.Select(h => h.Name).ToArray());
    Assert.AreEqual("from b", result[1].Value);
    Assert.AreEqual("i=1; rewse.jp; spf=pass", result[2].Value);
}

// GetEmailDetailsToolTests — provider returns
// new EmailMessage { Id = "email-1", AccountId = "acc-1", Headers = [new EmailHeader("ARC-Authentication-Results", "i=1; spf=pass")] }
[TestMethod]
public async Task GetEmailDetails_IncludesHeadersFromProvider()
{
    // ...
    Assert.IsTrue(doc.RootElement.TryGetProperty("headers", out var headers));
    Assert.AreEqual("ARC-Authentication-Results", headers[0].GetProperty("name").GetString());
    Assert.AreEqual("i=1; spf=pass", headers[0].GetProperty("value").GetString());
}

// provider returns TestData.CreateEmail(id: "email-1", accountId: "acc-1") (Headers is null)
[TestMethod]
public async Task GetEmailDetails_HeadersNullWhenProviderHasNone()
{
    // ...
    Assert.IsTrue(doc.RootElement.TryGetProperty("headers", out var headers));
    Assert.AreEqual(JsonValueKind.Null, headers.ValueKind);
}
```

- [ ] **Step 2: コンパイルだけ通す**

`EmailHeader` と `EmailMessage.Headers` を宣言し、`ToEmailHeaders` は空のリストを返すだけにする。ツールと詳細の組み立ては変えない。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter "ToEmailHeaders|GetEmailDetails"`
Expected: 新しい三つが FAIL（`ToEmailHeaders` は件数のアサーション、ツールの二つは `TryGetProperty` が false）。既存の `GetEmailDetails_*` は PASS

- [ ] **Step 4: 実装する**

`ToEmailHeaders` は各 `Header` の `Field` と `Value` をそのまま並べる。IMAP の詳細の組み立てで `Headers = ToEmailHeaders(m.Headers)` を設定する。ツールの応答に `headers = email.Headers?.Select(h => new { name = h.Name, value = h.Value })` を足し、説明文に IMAP ではヘッダーが付くこと（SPF、DKIM、DMARC の結果の確認向け）を書く。

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests && dotnet build src/CalendarMcp.HttpServer -c Release`
Expected: `Failed: 0` と `Build succeeded.`

- [ ] **Step 6: Commit と push**

```bash
git add src changelogs/2026-11-07-email-headers.md
git commit -m "Return email headers from get_email_details"
git push
```

Expected: `gh run watch -R rewse/calendar-mcp --exit-status "$(gh run list -R rewse/calendar-mcp -b rewse -L 1 --json databaseId -q '.[0].databaseId')"` が成功

### Task 16: ロールを fork からのビルドに切り替える

ansible-playbooks の `feat/calendar-mcp` で行う。

> Step 1 から 5（b15856dc）と、Step 6 の一回目の適用は fbc6950 の時点で実施済み。Step 6 は Task 17 の push のあとに一回目からやり直す。

**Files:**
- Modify: `roles/calendar_mcp/tasks/container.yml`、`tests/test_calendar_mcp.py`
- Delete: `roles/calendar_mcp/files/calendar-mcp.patch`

**Interfaces:**
- Consumes: Task 17 の時点の `rewse/calendar-mcp` の既定ブランチ
- Produces: `__calendar_mcp_source`（`{commit}`）、`__calendar_mcp_image`（`calendar-mcp:<commit の先頭 12 文字>`）。compose と handler は今のまま

- [ ] **Step 1: 失敗するテストを書く**

`CalendarMcpBuildTest` の `test_lookup_selects_release_commits`、`test_image_tag_changes_with_the_patch`、`test_patch_failure_stops_the_play`、`test_checkout_starts_clean` を消し、次を足す。

```python
def test_lookup_follows_the_fork_without_cooldown(self):
    fact = task_named("container.yml", "container | Resolve fork commit")[
        "ansible.builtin.set_fact"]["__calendar_mcp_source"]
    self.assertIn("github-commit:rewse/calendar-mcp", fact)
    self.assertIn("days=0", fact)

def test_image_tag_is_the_commit(self):
    fact = task_named("container.yml", "container | Name image")[
        "ansible.builtin.set_fact"]["__calendar_mcp_image"]
    self.assertIn("__calendar_mcp_source.commit[:12]", fact)
    self.assertNotIn("hash(", fact)

def test_checkout_is_the_fork(self):
    git = task_named("container.yml", "container | Check out repository")["ansible.builtin.git"]
    self.assertEqual(git["repo"], "https://github.com/rewse/calendar-mcp.git")
    self.assertIs(git["force"], True)

def test_no_patch_is_applied(self):
    self.assertNotIn("ansible.posix.patch", (ROLE / "tasks" / "container.yml").read_text())
    self.assertFalse((ROLE / "files" / "calendar-mcp.patch").exists())
```

`test_build_is_skipped_when_the_image_exists` の対象は `container | Check out repository` と `container | Build image` の二つにする。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -v`
Expected: 新しい四つが FAIL、`test_build_is_skipped_when_the_image_exists` は PASS

- [ ] **Step 3: 実装する**

`container.yml` で、lookup を `lookup('aged_release', 'github-commit:rewse/calendar-mcp', days=0)`、タスク名を `container | Resolve fork commit`、タグを `'calendar-mcp:' ~ __calendar_mcp_source.commit[:12]`、checkout を fork の URL と `force: true` にする。`container | Remove previous checkout` と `container | Apply patch` を消し、パッチのファイルを `git rm` する。lookup のコメントには、fork は自分のリポジトリなので待機期間なしで追い、上流のコードの待機期間は rebase の元を待機期間を過ぎた Release に限ることで守る、と書く。

- [ ] **Step 4: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: 失敗なし

- [ ] **Step 5: Commit**

```bash
git add -A roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "feat(calendar_mcp): build from the rewse fork instead of a patch"
```

- [ ] **Step 6: 適用する**

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`、続けてもう一度
Expected: 一回目は成功してイメージのタグが `calendar-mcp:<Task 17 の commit の先頭 12 文字>` に変わり、二回目は `changed=0`

- [ ] **Step 7: 家から確かめる**

Task 7 Step 4 の確認を `/tmp/calmcp-verify/mcp.py` でもう一度通す（トークンは `op read` から渡す。401 を五回続けると fail2ban が自分を BAN するので、トークンなしの確認は一回にとどめる）。加えて次を確かめる。

- `get_email_headers` で自分宛てのメールを読むと、`headers` に `ARC-Authentication-Results` と `Received` がある。同じメールの `get_email_details` の応答には `headers` がない
- `get_email_headers` に `ts-icloud` を渡すと `Failed to get email headers: This account does not support this operation.` が返る
- `save_draft` で自分宛ての下書きを一つ保存すると、IMAP の `INBOX.Draft` に `\Draft` 付きで一通増え、`INBOX.Sent` の件数は変わらない。確かめたらその下書きを消す

### Task 17: `get_email_headers`

`~/git/calendar-mcp` の `rewse` ブランチで、30936fe（fbc6950 の revert）の上に積む。Task 16 の Step 6 より前に行う。

**Files:**
- Create: `src/CalendarMcp.Core/Utilities/EmailHeaderMapper.cs`、`src/CalendarMcp.Core/Tools/GetEmailHeadersTool.cs`、`changelogs/2026-11-07-email-headers-tool.md`（`changelogs/2026-11-07-save-draft-tool.md` と同じ見出しの形）
- Modify: `src/CalendarMcp.Core/Models/EmailMessage.cs`
- Modify: `src/CalendarMcp.Core/Providers/ImapProviderService.cs`（`MessageToEmail` を `internal` にする）、`GoogleProviderService.cs`（`ConvertToEmailMessage` を `internal static` にする。インスタンスの状態は使っていない）、`M365ProviderService.cs` と `OutlookComProviderService.cs`（どちらも `GetEmailDetailsAsync` の `EmailMessage` の組み立て）
- Modify: `src/CalendarMcp.HttpServer/Program.cs`、`src/CalendarMcp.StdioServer/Program.cs`（どちらも `GetEmailDetailsTool` の次に登録）
- Test: `src/CalendarMcp.Tests/Utilities/EmailHeaderMapperTests.cs`、`src/CalendarMcp.Tests/Providers/GoogleEmailConversionTests.cs`、`src/CalendarMcp.Tests/Tools/GetEmailHeadersToolTests.cs`（三つとも新規）、`src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`、`src/CalendarMcp.Tests/Tools/PermissionEnforcementTests.cs`

**Interfaces:**
- Produces: `public sealed record EmailHeader(string Name, string Value)`（`EmailMessage.cs`）と `EmailMessage.Headers`（`List<EmailHeader>?`、既定 null）。null はプロバイダーがヘッダーを返さないこと、空の並びはヘッダーのないメールを表す。詳細を取るときだけ埋め、一覧と検索では null のまま
- Produces: `public static class EmailHeaderMapper`（`CalendarMcp.Core.Utilities`）の `List<EmailHeader> FromMime(MimeKit.HeaderList headers)`、`List<EmailHeader> FromGraph(IEnumerable<Microsoft.Graph.Models.InternetMessageHeader>? headers)`、`List<EmailHeader> FromGmail(IEnumerable<Google.Apis.Gmail.v1.Data.MessagePartHeader>? headers)`。どれも入力の順を保ち、null の入力は空の並び、null の `Name` と `Value` は空文字にする
- Produces: `public sealed class GetEmailHeadersTool(IAccountRegistry, IProviderServiceFactory, ILogger<GetEmailHeadersTool>)` の `Task<string> GetEmailHeaders(string accountId, string emailId)`。MCP の名前は `get_email_headers`。応答は `{"headers": [{"name": ..., "value": ...}]}`（`WriteIndented`、`get_unsubscribe_info` と同じ）
- `get_email_details` の応答と説明文は変えない

- [ ] **Step 1: 失敗するテストを書く**

`EmailHeaderMapperTests.cs`:

```csharp
[TestMethod]
public void FromMime_KeepsEveryFieldInOrder()
{
    var headers = new MimeKit.HeaderList
    {
        { "Received", "from a" },
        { "Received", "from b" },
        { "ARC-Authentication-Results", "i=1; rewse.jp; spf=pass" },
    };
    var result = EmailHeaderMapper.FromMime(headers);
    CollectionAssert.AreEqual(new[] { "Received", "Received", "ARC-Authentication-Results" },
        result.Select(h => h.Name).ToArray());
    Assert.AreEqual("from b", result[1].Value);
    Assert.AreEqual("i=1; rewse.jp; spf=pass", result[2].Value);
}

[TestMethod]
public void FromGraph_KeepsEveryFieldInOrder()
{
    var result = EmailHeaderMapper.FromGraph(
    [
        new InternetMessageHeader { Name = "Received", Value = "from a" },
        new InternetMessageHeader { Name = "Received", Value = "from b" },
        new InternetMessageHeader { Name = "Authentication-Results", Value = "spf=pass" },
    ]);
    CollectionAssert.AreEqual(new[] { "Received", "Received", "Authentication-Results" },
        result.Select(h => h.Name).ToArray());
    Assert.AreEqual("from b", result[1].Value);
}

[TestMethod]
public void FromGraph_Null_ReturnsEmpty()
{
    Assert.AreEqual(0, EmailHeaderMapper.FromGraph(null).Count);
}

[TestMethod]
public void FromGmail_KeepsEveryFieldInOrder()
{
    var result = EmailHeaderMapper.FromGmail(
    [
        new MessagePartHeader { Name = "Received", Value = "from a" },
        new MessagePartHeader { Name = "Authentication-Results", Value = "mx.google.com; spf=pass" },
    ]);
    CollectionAssert.AreEqual(new[] { "Received", "Authentication-Results" },
        result.Select(h => h.Name).ToArray());
    Assert.AreEqual("mx.google.com; spf=pass", result[1].Value);
}
```

`GoogleEmailConversionTests.cs`（`GmailMessage()` は `Id = "m1"`、`Payload = new MessagePart { MimeType = "text/plain", Headers = [Received: from a、Authentication-Results: mx.google.com; spf=pass、Subject: s] }` の `Message` を返す補助）:

```csharp
[TestMethod]
public void ConvertToEmailMessage_Details_IncludesHeaders()
{
    var email = GoogleProviderService.ConvertToEmailMessage(GmailMessage(), "acc-1", includeBody: true);
    Assert.IsNotNull(email.Headers);
    CollectionAssert.AreEqual(new[] { "Received", "Authentication-Results", "Subject" },
        email.Headers.Select(h => h.Name).ToArray());
}

[TestMethod]
public void ConvertToEmailMessage_List_LeavesHeadersNull()
{
    Assert.IsNull(GoogleProviderService.ConvertToEmailMessage(GmailMessage(), "acc-1").Headers);
}
```

`ImapProviderServiceTests.cs`:

```csharp
[TestMethod]
public void MessageToEmail_IncludesEveryHeader()
{
    var m = new MimeMessage();
    m.From.Add(MailboxAddress.Parse("a@example.com"));
    m.Headers.Add("Received", "from a");
    m.Headers.Add("ARC-Authentication-Results", "i=1; spf=pass");
    m.Subject = "s";
    m.Body = new TextPart("plain") { Text = "b" };

    var email = ImapProviderService.MessageToEmail(m, "INBOX", 1, 2, "acc-1", isRead: true);

    Assert.IsNotNull(email.Headers);
    CollectionAssert.AreEqual(m.Headers.Select(h => h.Field).ToArray(),
        email.Headers.Select(h => h.Name).ToArray());
}
```

`GetEmailHeadersToolTests.cs`（`GetUnsubscribeInfoToolTests` と同じ組み立て。アカウントは `TestData.CreateAccount(id: "acc-1", provider: "imap")`、プロバイダーの `GetEmailDetailsAsync("acc-1", <emailId>, Arg.Any<CancellationToken>())` に返り値を設定する）:

```csharp
GetEmailHeaders_EmptyAccountId_ThrowsMcpException
    // ex.Message == "accountId is required"
GetEmailHeaders_EmptyEmailId_ThrowsMcpException
    // ex.Message == "emailId is required"
GetEmailHeaders_EmailNotFound_ThrowsMcpException
    // provider returns null for "missing"; ex.Message == "Email 'missing' not found in account 'acc-1'"

[TestMethod]
public async Task GetEmailHeaders_ReturnsHeadersInOrder()
{
    // provider returns new EmailMessage { Id = "email-1", AccountId = "acc-1", Headers =
    //     [new("Received", "from a"), new("Received", "from b"), new("ARC-Authentication-Results", "i=1; spf=pass")] }
    var headers = JsonDocument.Parse(await tool.GetEmailHeaders("acc-1", "email-1"))
        .RootElement.GetProperty("headers");
    Assert.AreEqual(3, headers.GetArrayLength());
    Assert.AreEqual("from b", headers[1].GetProperty("value").GetString());
    Assert.AreEqual("ARC-Authentication-Results", headers[2].GetProperty("name").GetString());
    regExp.Verify(); factExp.Verify(); provExp.Verify();
}

GetEmailHeaders_MessageWithoutHeaders_ReturnsEmptyArray
    // Headers = []; headers.GetArrayLength() == 0
GetEmailHeaders_ProviderWithoutHeaders_ThrowsMcpException
    // provider returns TestData.CreateEmail(id: "email-1", accountId: "acc-1") (Headers is null)
    // ex.Message == "Account 'acc-1' does not provide email headers"
GetEmailHeaders_DavAccount_ThrowsMcpException
    // account provider "dav"; GetEmailDetailsAsync .Callback((_, _, _) => throw new NotSupportedException(
    //     "DAV provider does not support email. Use an IMAP account for mail."))
    // ex.Message == "Failed to get email headers: This account does not support this operation."
```

`PermissionEnforcementTests.cs`（`SaveDraft_AccountWithoutEmailRead_Throws` と同じ形）:

```csharp
GetEmailHeaders_AccountWithoutEmailRead_Throws
    // Scoped("cal-only", AccountPermission.CalendarRead, provider: "imap"); provider factory with no setups
    // McpException whose message contains "does not permit reading email"
```

- [ ] **Step 2: コンパイルだけ通す**

`EmailHeader` と `EmailMessage.Headers` を宣言する。`EmailHeaderMapper` の三つは `throw new NotImplementedException();`、`GetEmailHeadersTool.GetEmailHeaders` の本体も `throw new NotImplementedException();` にする。`MessageToEmail` を `internal`、`ConvertToEmailMessage` を `internal static` にする。プロバイダーの組み立てと `Program.cs` は変えない。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter "EmailHeaderMapper|ConvertToEmailMessage|MessageToEmail|GetEmailHeaders"`
Expected: `ConvertToEmailMessage_List_LeavesHeadersNull` だけ PASS（一覧で埋めないことを固定するテストで、今の実装でも通る）。ほかの十四は FAIL。`EmailHeaderMapper` の四つとツールの八つ（`PermissionEnforcementTests` の一つを含む）は `NotImplementedException`（ツールのテストは期待した `McpException` でないため）、`ConvertToEmailMessage_Details_IncludesHeaders` と `MessageToEmail_IncludesEveryHeader` は `Assert.IsNotNull` で落ちる

- [ ] **Step 4: 実装する**

- `EmailHeaderMapper`: 入力の各要素から `EmailHeader` を作って並べる。`FromMime` は `Header.Field` と `Header.Value`
- `ImapProviderService.MessageToEmail`: `Headers = EmailHeaderMapper.FromMime(m.Headers)`
- `GoogleProviderService.ConvertToEmailMessage`: `Headers = includeBody ? EmailHeaderMapper.FromGmail(headers) : null`
- `M365ProviderService` と `OutlookComProviderService` の `GetEmailDetailsAsync`: `Headers = EmailHeaderMapper.FromGraph(message.InternetMessageHeaders)`。どちらも詳細の取得で `internetMessageHeaders` をもう `Select` している。Graph を呼ぶ部分なので単体テストはなく、この一行はレビューで読む
- `GetEmailHeadersTool.GetEmailHeaders`: `GetUnsubscribeInfoTool` と同じ順で `ToolGuard.RequireNonEmpty`（`accountId`、`emailId`）、`ToolGuard.RequireAccountAsync(..., AccountPermission.EmailRead)`、`GetEmailDetailsAsync`。null なら `Email '<emailId>' not found in account '<accountId>'`、`Headers` が null なら `Account '<accountId>' does not provide email headers` の `McpException`。ほかの例外は `ToolGuard.Failure("get email headers", ex)`。説明文には、すべてのヘッダーをメッセージの順で返すこと、認証の結果（`Authentication-Results`、`ARC-Authentication-Results` の SPF、DKIM、DMARC）と経路（`Received`）の確認に使うこと、`accountId` と `emailId` は `get_emails` か `search_emails` の結果から取ることを書く
- 二つの `Program.cs` に登録し、changelog に、`get_email_details` の応答を膨らませないために別のツールにしたこと、四つのプロバイダーで詳細の取得のときだけヘッダーを埋めることを書く。`docs/mcp-tools.md` と `src/CalendarMcp.Core/Skills/email.md` は、上流に PR を出すときに `save_draft` とあわせて書く（設計のとおり）

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests && dotnet build src/CalendarMcp.HttpServer -c Release && dotnet build src/CalendarMcp.StdioServer -c Release`
Expected: `Failed: 0`（798 件）と、二つの `Build succeeded.`

- [ ] **Step 6: Commit と push**

```bash
git add src changelogs/2026-11-07-email-headers-tool.md
git commit -m "Add a get_email_headers tool"
git push
```

Expected: 30936fe と新しいコミットが push され、`gh run watch -R rewse/calendar-mcp --exit-status "$(gh run list -R rewse/calendar-mcp -b rewse -L 1 --json databaseId -q '.[0].databaseId')"` が成功

### Task 18: IMAP の UID を古い順で FETCH する

`~/git/calendar-mcp` の `rewse` ブランチで、f611c90（`get_email_headers`）の上に積む。

**Files:**
- Modify: `src/CalendarMcp.Core/Providers/ImapProviderService.cs`（`GetEmailsAsync`、`SearchEmailsAsync`、新しい `NewestUids`）
- Create: `changelogs/2026-11-07-imap-ascending-uid-fetch.md`（`changelogs/2026-11-07-save-draft-tool.md` と同じ見出しの形）
- Test: `src/CalendarMcp.Tests/Providers/ImapProviderServiceTests.cs`

**Interfaces:**
- Produces: `internal static IList<UniqueId> ImapProviderService.NewestUids(IEnumerable<UniqueId> uids, int count)`。値の大きい順に `count` 個を選び、古い順（昇順）に並べて返す。`GetEmailsAsync` と `SearchEmailsAsync` は、これを `FetchAsync` に渡す
- 応答の並び（日付の新しい順）と件数の上限は変えない

- [ ] **Step 1: 失敗するテストを書く**

`ImapProviderServiceTests.cs`（`UniqueIdSet.ToString` は MailKit が FETCH に書く UID の文字列を作る）:

```csharp
private static IEnumerable<MailKit.UniqueId> Uids(params uint[] ids) =>
    ids.Select(id => new MailKit.UniqueId(id));

[TestMethod]
public void NewestUids_SendsAscendingRanges()
{
    // Courier-IMAP answers a reversed range such as 36045:36043 with one message.
    var newest = ImapProviderService.NewestUids(Uids(36026, 36027, 36043, 36044, 36045, 36047, 36050), 5);

    Assert.AreEqual("36043:36045,36047,36050", MailKit.UniqueIdSet.ToString(newest));
}

[TestMethod]
public void NewestUids_CountAboveTotal_ReturnsEveryUid()
{
    var newest = ImapProviderService.NewestUids(Uids(7, 3, 5), 20);

    Assert.AreEqual("3,5,7", MailKit.UniqueIdSet.ToString(newest));
}
```

- [ ] **Step 2: 今の選び方をそのまま `NewestUids` に移す**

`NewestUids` の本体を今の二か所と同じ `uids.OrderByDescending(u => u.Id).Take(count).ToList()` にし、`GetEmailsAsync` と `SearchEmailsAsync` からそれを呼ぶ。振る舞いはまだ変えない。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter NewestUids`
Expected: 二つとも FAIL。`Expected:<36043:36045,36047,36050>. Actual:<36050,36047,36045:36043>` と `Expected:<3,5,7>. Actual:<7,5,3>`（今の並びが逆順の範囲を作ることの確認）

- [ ] **Step 4: 実装する**

`NewestUids` で、選んだ UID を昇順に並べ直して返す。メソッドのコメントに、Courier-IMAP は `5:3` のような逆順の範囲に 1 通しか返さないので、FETCH には昇順で渡すこと（RFC 3501 では `5:3` と `3:5` は同じ）を書く。changelog に、症状（`get_emails` が頼んだ件数より少なく返る）、原因、応答の並びは変わらないことを書く。

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests && dotnet build src/CalendarMcp.HttpServer -c Release`
Expected: `Failed: 0`（801 件）と `Build succeeded.`

- [ ] **Step 6: Commit と push**

```bash
git add src changelogs/2026-11-07-imap-ascending-uid-fetch.md
git commit -m "Fetch IMAP messages in ascending UID order"
git push
```

Expected: `gh run watch -R rewse/calendar-mcp --exit-status "$(gh run list -R rewse/calendar-mcp -b rewse -L 1 --json databaseId -q '.[0].databaseId')"` が成功

- [ ] **Step 7: 適用する**

ansible-playbooks で Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`、続けてもう一度
Expected: 一回目でイメージのタグが `calendar-mcp:<Step 6 の commit の先頭 12 文字>` に変わり、二回目は `changed=0`。二つのコンテナが healthy

- [ ] **Step 8: 家から確かめる**

`/tmp/calmcp-verify/mcp.py` で ts のトークンを使う。生の IMAP の確認は、Sakura のユーザー名とパスワードを `op read` から標準入力で渡すスクリプト（`/tmp/calmcp-verify/imapsearch.py` と同じ形）で行う。

- `get_emails`（`ts-sakura`、count 5）が 5 件を返し、その ID の UID が、生の IMAP の `UID SEARCH ALL` の最後の 5 個と一致する。並びは日付の新しい順
- `get_emails`（count 20）が 20 件を返す
- `search_emails`（query `Amazon`、count 10）が返す UID が、生の IMAP の `UID SEARCH OR OR SUBJECT Amazon BODY Amazon FROM Amazon` の最後の 10 個（ヒットが 10 件未満なら全部）と一致する

確かめたら、Task 8 を完了にする。

### Task 19: .NET のベースイメージを `aged_release` で固定する

前半は `~/git/calendar-mcp` の `rewse`（08680d8 の上）、後半は ansible-playbooks の `feat/calendar-mcp` で行う。

**Files:**
- Modify（fork）: `Dockerfile`、`README.md`（「HTTP Server (Containerized)」の `docker build` の例）
- Create（fork）: `changelogs/2026-11-07-dockerfile-base-image-args.md`（`changelogs/2026-11-07-save-draft-tool.md` と同じ見出しの形）
- Modify: `roles/calendar_mcp/tasks/container.yml`（`container | Resolve SDK image` と `container | Resolve runtime image` を `container | Resolve fork commit` の次に足し、`container | Name image` と `container | Build image` を変える）、`roles/calendar_mcp/vars/main.yml`（`calendar_mcp_container_dotnet_version`）、`roles/calendar_mcp/templates/compose.yaml.j2`（古いコメント）
- Test: `tests/test_calendar_mcp.py`（`CalendarMcpBuildTest`）

**Interfaces:**
- Produces（fork）: `Dockerfile` の最初の `FROM` の前に `ARG SDK_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0` と `ARG RUNTIME_IMAGE=mcr.microsoft.com/dotnet/aspnet:10.0`。二つの段は `FROM ${SDK_IMAGE} AS build` と `FROM ${RUNTIME_IMAGE} AS runtime`
- Produces: `calendar_mcp_container_dotnet_version: "10.0"`（fork の `TargetFramework` の `net10.0` に合わせた固定。理由をコメントに書く）
- Produces: `__calendar_mcp_sdk_image` と `__calendar_mcp_runtime_image`（どちらも `aged_release` の `oci:` の返り値 `{version, ref}`。`ref` は `repo:tag@digest`）
- Produces: `__calendar_mcp_image` は `'calendar-mcp:' ~ __calendar_mcp_source.commit[:12] ~ '-' ~ ((__calendar_mcp_sdk_image.ref ~ ' ' ~ __calendar_mcp_runtime_image.ref) | hash('sha256'))[:12]`

- [ ] **Step 1: fork の `Dockerfile` を変える**

二つの `ARG` を最初の `FROM` の前に置き、二つの `FROM` をそれに替える。既定値は今の `FROM` と同じにして、引数なしのビルドは変わらないようにする。changelog に、ビルドする側がベースを `tag@digest` で固定できるようにしたことを書く。`README.md` の `docker build` の例の下に、`--build-arg SDK_IMAGE=...` と `--build-arg RUNTIME_IMAGE=...` でベースを固定できることを一文と例で書く。

- [ ] **Step 2: fork を Commit と push**

```bash
git add Dockerfile README.md changelogs/2026-11-07-dockerfile-base-image-args.md
git commit -m "Allow overriding the .NET base images in the Dockerfile"
git push
```

Expected: fork の CI が成功。`dotnet test` は `Dockerfile` を使わないので、`Dockerfile` そのものは Step 8 のビルドで確かめる

- [ ] **Step 3: 失敗するテストを書く**

`render_expression(expression, **facts)` を test ファイルの補助として足す（jinja2 の `Environment` に `hash` フィルターを `hashlib` で足し、`{{ ... }}` を描画する）。`test_image_tag_is_the_commit` を最初のテストに置き換え、二つを足す。

```python
def test_image_tag_joins_the_commit_and_the_base_images(self):
    expression = task_named("container.yml", "container | Name image")[
        "ansible.builtin.set_fact"]["__calendar_mcp_image"]
    sdk = "mcr.microsoft.com/dotnet/sdk:10.0.402@sha256:aaa"
    runtime = "mcr.microsoft.com/dotnet/aspnet:10.0.13@sha256:bbb"
    tag = render_expression(expression,
        __calendar_mcp_source={"commit": "08680d87ba0918b8e10c3302ce6c02b58516b94b"},
        __calendar_mcp_sdk_image={"ref": sdk}, __calendar_mcp_runtime_image={"ref": runtime})
    self.assertEqual(tag, "calendar-mcp:08680d87ba09-"
                     + hashlib.sha256(f"{sdk} {runtime}".encode()).hexdigest()[:12])

def test_base_images_are_aged_releases_of_the_target_framework(self):
    for name, var, repo in (
        ("container | Resolve SDK image", "__calendar_mcp_sdk_image", "oci:mcr.microsoft.com/dotnet/sdk"),
        ("container | Resolve runtime image", "__calendar_mcp_runtime_image", "oci:mcr.microsoft.com/dotnet/aspnet"),
    ):
        fact = task_named("container.yml", name)["ansible.builtin.set_fact"][var]
        self.assertIn(repo, fact)
        self.assertIn("calendar_mcp_container_dotnet_version", fact)
        self.assertNotIn("days=", fact)  # the default supply-chain cooldown applies
    self.assertEqual(role_vars()["calendar_mcp_container_dotnet_version"], "10.0")

def test_build_passes_the_pinned_base_images(self):
    build = task_named("container.yml", "container | Build image")["community.docker.docker_image_build"]
    self.assertEqual(build["args"], {
        "SDK_IMAGE": "{{ __calendar_mcp_sdk_image.ref }}",
        "RUNTIME_IMAGE": "{{ __calendar_mcp_runtime_image.ref }}",
    })
```

- [ ] **Step 4: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_calendar_mcp.py -q -k "base_images or image_tag"`
Expected: 三つとも FAIL（タグの描画はアサーション、二つの `Resolve` タスクは `StopIteration`、`args` は `KeyError`）

- [ ] **Step 5: 実装する**

二つの `Resolve` タスクは `lookup('aged_release', 'oci:mcr.microsoft.com/dotnet/<sdk か aspnet>', pattern='^' ~ (calendar_mcp_container_dotnet_version | regex_escape) ~ '\.\d+$', platform=...)`。`platform` はほかのロールと同じく `ansible_facts['architecture']` から決める。`Name image` を Interfaces の式にし、`Build image` に `args` を足す。`container | Resolve fork commit` のコメントの fork の変更の一覧に UID の並びとベースイメージを足し、`compose.yaml.j2` の「source component」を「container component」に直す（最終レビューの Minor のうち、このタスクで触れるファイルにあるもの）。

- [ ] **Step 6: 通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q` と `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: どちらも通る

- [ ] **Step 7: Commit**

```bash
git add roles/calendar_mcp tests/test_calendar_mcp.py
git commit -m "fix(calendar_mcp): pin and refresh the .NET base images"
```

- [ ] **Step 8: 適用して確かめる**

Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`、終わってからもう一度（二つを同時に流さない）
Expected: 一回目でイメージのタグが `calendar-mcp:<Step 2 の commit の先頭 12 文字>-<12 文字>` になり、二つのコンテナが healthy。二回目は `changed=0`。`docker run --rm --entrypoint dotnet <image> --list-runtimes` の `Microsoft.AspNetCore.App` の版が、`aged_release` の選んだ `aspnet` のタグと同じ。家から `get_emails`（count 5）と `get_email_headers` をもう一度通す

### Task 20: 招待メールが出る予定の操作に `emailSend` を求める

`~/git/calendar-mcp` の `rewse` ブランチで、Task 19 の fork のコミットの上に積む。fox への反映は最後の Step で行う。

**Files:**
- Modify: `src/CalendarMcp.Core/Tools/ToolGuard.cs`（`HasAttendees`、`RequireEmailSendIfEventHasAttendeesAsync`）、`CreateEventTool.cs`、`UpdateEventTool.cs`、`DeleteEventTool.cs`、`RespondToEventTool.cs`（権限の確かめ方と説明文）
- Modify: `README.md`（権限の表）、`docs/mcp-tools.md`（「Account permissions」の表と本文、四つのツールの節）、`docs/configuration.md`（`emailSend` の行と Notes）、`docs/security.md`（「Per-Account Permissions」の脅威モデルの箇条）、`src/CalendarMcp.Core/Skills/calendar.md`（参加者と返事に `emailSend` が要ること、拒否されたら利用者にカレンダーのアプリでの操作を頼むこと）
- Create: `changelogs/2026-11-07-calendar-invitations-need-email-send.md`（`changelogs/2026-11-07-save-draft-tool.md` と同じ見出しの形）
- Test: `src/CalendarMcp.Tests/Tools/ToolGuardTests.cs`、`src/CalendarMcp.Tests/Tools/PermissionEnforcementTests.cs`

**Interfaces:**
- Produces: `internal static bool ToolGuard.HasAttendees(CalendarEvent evt)`。`evt.Attendees` か `evt.AttendeeDetails` が空でなければ true。`Organizer` は見ない
- Produces: `internal static async Task ToolGuard.RequireEmailSendIfEventHasAttendeesAsync(IProviderService provider, AccountInfo account, string calendarId, string eventId)`。アカウントが `EmailSend` を持てば何も読まずに戻る。持たなければ `GetCalendarEventDetailsAsync` で予定を読み、null なら `Event '<eventId>' not found in account '<accountId>'`、`HasAttendees` が true なら `RequirePermission(account, AccountPermission.EmailSend)` の例外を投げる
- 振る舞い（設計の「招待の制限」）: `create_event` は `attendees` が空でないとき、`update_event` は `attendees` が null でないときに `RequirePermission(account, EmailSend)`。`update_event` と `delete_event` は、そのあと `RequireEmailSendIfEventHasAttendeesAsync`。`respond_to_event` はいつも `EmailSend` を求める。`accountId` を省いた振り分けでは、`create_event`（参加者あり）と `respond_to_event` は `CalendarWrite` と `EmailSend` の両方で絞る。`delete_event` の振り分けは今のまま `CalendarWrite` で選び、選んだアカウントに `RequireEmailSendIfEventHasAttendeesAsync` をかける

- [ ] **Step 1: 失敗するテストを書く**

`ToolGuardTests.cs`:

```csharp
[TestMethod]
public void HasAttendees_ReadsBothAttendeeLists()
{
    Assert.IsTrue(ToolGuard.HasAttendees(new CalendarEvent { Id = "e", AccountId = "a", Attendees = ["x@example.com"] }));
    Assert.IsTrue(ToolGuard.HasAttendees(new CalendarEvent { Id = "e", AccountId = "a",
        AttendeeDetails = [new EventAttendee { Email = "x@example.com" }] }));
    // M365 sets an organizer on events nobody else attends.
    Assert.IsFalse(ToolGuard.HasAttendees(new CalendarEvent { Id = "e", AccountId = "a", Organizer = "me@example.com" }));
}
```

`PermissionEnforcementTests.cs`（`Permits(id, provider, params AccountPermission[])` を補助として足す。`AccountPermissions.None` に `With` を重ねる。プロバイダーの呼び出しを期待しないテストは、セットアップのない `IProviderServiceCreateExpectations` を渡し、予期しない呼び出しで Rocks が落ちることで「呼ばない」を確かめる）:

```csharp
CreateEvent_AttendeesWithoutEmailSend_Throws
    // Permits("cal", "dav", CalendarWrite); attendees ["x@example.com"]; message contains "does not permit sending email"
CreateEvent_AttendeesWithEmailSend_Creates
    // Permits("both", "dav", CalendarWrite, EmailSend); CreateEventAsync returns "evt-1"; success
CreateEvent_NoAttendeesWithoutEmailSend_Creates
    // Permits("cal", "dav", CalendarWrite); attendees null; CreateEventAsync returns "evt-1"; success
CreateEvent_NoAccountIdWithAttendees_PicksAnAccountThatPermitsSending
    // GetAllAccountsAsync → [Permits("cal", "dav", CalendarWrite), Permits("both", "dav", CalendarWrite, EmailSend)]; accountUsed == "both"
UpdateEvent_AttendeesWithoutEmailSend_Throws
    // Permits("cal", "dav", CalendarWrite); attendees []; no provider call; "does not permit sending email"
UpdateEvent_EventWithAttendeesWithoutEmailSend_Throws
    // GetCalendarEventDetailsAsync("cal", "c1", "e1") → event with Attendees ["x@example.com"]; UpdateEventAsync not set up
UpdateEvent_EventWithoutAttendeesWithoutEmailSend_Updates
    // details → event without attendees; UpdateEventAsync set up; success
UpdateEvent_WithEmailSend_DoesNotReadTheEvent
    // Permits("both", "dav", CalendarWrite, EmailSend); only UpdateEventAsync set up; success
DeleteEvent_EventWithAttendeesWithoutEmailSend_Throws
    // details → event with AttendeeDetails; DeleteEventAsync not set up; "does not permit sending email"
DeleteEvent_EventWithoutAttendeesWithoutEmailSend_Deletes
    // details → event without attendees; DeleteEventAsync set up; success
DeleteEvent_MissingEventWithoutEmailSend_Throws
    // details → null; message == "Event 'e1' not found in account 'cal'"
RespondToEvent_WithoutEmailSend_Throws
    // Permits("cal", "dav", CalendarWrite); "does not permit sending email"; no provider call
RespondToEvent_WithEmailSend_Responds
    // Permits("both", "dav", CalendarWrite, EmailSend); RespondToEventAsync set up; success
```

- [ ] **Step 2: コンパイルだけ通す**

`HasAttendees` は `false` を返し、`RequireEmailSendIfEventHasAttendeesAsync` は `Task.CompletedTask` を返すだけにする。ツールは変えない。

- [ ] **Step 3: 失敗を確かめる**

Run: `dotnet test src/CalendarMcp.Tests --filter "HasAttendees|PermissionEnforcementTests"`
Expected: 新しいテストのうち十が FAIL。拒否を期待する六つ（`*_Throws`）、`HasAttendees_ReadsBothAttendeeLists`、`CreateEvent_NoAccountIdWithAttendees_PicksAnAccountThatPermitsSending`（`cal` が選ばれ、Rocks が予期しない呼び出しで落ちる）、予定を読むことを期待する `UpdateEvent_EventWithoutAttendeesWithoutEmailSend_Updates` と `DeleteEvent_EventWithoutAttendeesWithoutEmailSend_Deletes`（`Verify` で落ちる）。残りの四つ（`CreateEvent_AttendeesWithEmailSend_Creates`、`CreateEvent_NoAttendeesWithoutEmailSend_Creates`、`UpdateEvent_WithEmailSend_DoesNotReadTheEvent`、`RespondToEvent_WithEmailSend_Responds`）は今の実装でも PASS（拒否しすぎないことを固定するテスト）。既存の `PermissionEnforcementTests` は PASS

- [ ] **Step 4: 実装する**

Interfaces のとおりに `ToolGuard` と四つのツールを変える。権限の確かめはどれもプロバイダーの書き込みより前に置く。説明文には、`create_event` と `update_event` の `attendees` に「参加者には招待がメールで届くので、アカウントに `emailSend` が要る」、`update_event` と `delete_event` に「参加者のいる予定を変えると参加者にメールが届くので `emailSend` が要る」、`respond_to_event` に「主催者に返事がメールで届くので `emailSend` が要る」を書く。`docs/mcp-tools.md` の表の `emailSend` の行にこの四つの条件を足し、表の下に「`emailSend` はアカウントの代わりに新しいメールを出すことすべてで、サーバーが送る招待、変更、取り消し、返事も含む」を書く。`README.md` と `docs/configuration.md` の権限の表の `emailSend` の行、`docs/configuration.md` の Notes、`docs/security.md` の脅威モデルの箇条も同じ内容にし、`docs/mcp-tools.md` の四つのツールの節と `Skills/calendar.md` に条件を書く。changelog に、iCloud が CalDAV の書き込みを受けて招待を送り、`SCHEDULE-AGENT=CLIENT` を無視することを書く

- [ ] **Step 5: 通ることを確かめる**

Run: `dotnet test src/CalendarMcp.Tests && dotnet build src/CalendarMcp.HttpServer -c Release`
Expected: `Failed: 0` と `Build succeeded.`

- [ ] **Step 6: Commit と push**

```bash
git add README.md src docs changelogs/2026-11-07-calendar-invitations-need-email-send.md
git commit -m "Require emailSend for calendar operations that mail attendees"
git push
```

Expected: fork の CI が成功

- [ ] **Step 7: 適用して家から確かめる**

ansible-playbooks で Run: `direnv exec . ansible-playbook home-primary.yml --tags calendar_mcp`、終わってからもう一度
Expected: 一回目でイメージのタグのコミットの部分が Step 6 のコミットになり、二回目は `changed=0`

ts のトークンで次を確かめる。参加者のいる予定は、主催者を付けずに `ATTENDEE` だけを持つ予定を CalDAV で直接 PUT して作る（主催者がいないので iCloud は招待を送らない）。確かめたら CalDAV で消す。

- `create_event` に `attendees`（`rewselab1@gmail.com`）を付けると `does not permit sending email` で拒否され、予定は増えない
- 参加者のいない予定の `create_event`、`update_event`、`delete_event` は通る
- 上の参加者のいる予定への `update_event` と `delete_event` は拒否され、予定は残る
- `respond_to_event` は拒否される

### Task 21: `save_draft` と `get_email_headers` の文書

`~/git/calendar-mcp` の `rewse` ブランチで、Task 20 の fork のコミットの上に積む。文書だけのコミットを二つ足す（設計の「文書」。既定ブランチは書き換えず、PR のブランチを作るときに機能のコミットとまとめる）。文書にはテストを書かない。英語で書き、書き上げたら `~/.agents/skills/humanizer/SKILL.md` の型を取り除く。

**Files:**
- Modify: `README.md`（「MCP Tools」の一覧）、`docs/mcp-tools.md`（ツールの節と「Account permissions」の表の `emailRead` の行）、`src/CalendarMcp.Core/Skills/overview.md`（ツールの一覧）、`src/CalendarMcp.Core/Skills/email.md`
- Modify（`save_draft` だけ）: `docs/IMAP-SETUP.md`（下書きの置き場所の決まり方）、`src/CalendarMcp.Core/Skills/providers.md`（`save_draft` は IMAP だけ）

**Interfaces:**
- Consumes: Task 14 の `save_draft`（引数、応答 `{success, accountId, draftEmailId, message}`、`emailRead`、IMAP のみ）と Task 17 の `get_email_headers`（引数、応答 `{"headers": [{name, value}]}`、`emailRead`、詳細を取るときだけ埋めるプロバイダー四つ、ヘッダーを返さないプロバイダーではエラー）。どちらもツールの `Description` と changelog の文言を正とする

- [ ] **Step 1: `save_draft` の文書を書く**

`README.md` の一覧で `send_email` の次に `save_draft`（送らずに下書きフォルダーへ保存する、返信なら元のメールにつながる）を足す。`docs/mcp-tools.md` は `send_email` の節の次に `#### \`save_draft\`` を置き、ほかの節と同じ形（説明、引数、応答の例）で書く。権限の表の `emailRead` の行に `save_draft` を足し、表の下の「Mailbox management ... sits under `emailRead`」の文に下書きを含める。`docs/IMAP-SETUP.md` には、下書きは `draftsFolder`、なければ SPECIAL-USE の `\Drafts` に置くことを書く。`Skills/overview.md` の一覧と `Skills/email.md` に、返事を頼まれて送信できないアカウントでは `save_draft` で下書きにし、送るのは利用者に任せることを書く。`Skills/providers.md` に、`save_draft` は IMAP だけで、ほかのプロバイダーでは使えないことを書く。

- [ ] **Step 2: 確かめて Commit**

Run: `rg -n '^#### \`save_draft\`' docs/mcp-tools.md && rg -n 'save_draft' README.md src/CalendarMcp.Core/Skills/overview.md src/CalendarMcp.Core/Skills/email.md src/CalendarMcp.Core/Skills/providers.md docs/IMAP-SETUP.md && dotnet test src/CalendarMcp.Tests`
Expected: どのファイルにも `save_draft` があり、テストは `Failed: 0`（`Skills/*.md` は埋め込みリソースなので、ビルドが通ることも確かめる）

```bash
git add README.md docs src/CalendarMcp.Core/Skills
git commit -m "Document the save_draft tool"
```

- [ ] **Step 3: `get_email_headers` の文書を書く**

`README.md` の一覧で `get_email_details` の次に `get_email_headers`（すべてのヘッダーをメッセージの順で返す。SPF、DKIM、DMARC の結果と経路の確認に使う）を足す。`docs/mcp-tools.md` は `get_email_details` の節の次に `#### \`get_email_headers\`` を置き、IMAP、Microsoft 365、Outlook.com、Google が返し、ほかのプロバイダーではエラーになることを書く。権限の表の `emailRead` の行に足す。`Skills/overview.md` の一覧と `Skills/email.md` に、迷惑メールやなりすましを疑うときは本文より先に `get_email_headers` で `Authentication-Results`、`ARC-Authentication-Results`、`Received` を見ることを書く。

- [ ] **Step 4: 確かめて Commit と push**

Run: `rg -n '^#### \`get_email_headers\`' docs/mcp-tools.md && rg -n 'get_email_headers' README.md src/CalendarMcp.Core/Skills/overview.md src/CalendarMcp.Core/Skills/email.md && dotnet test src/CalendarMcp.Tests`
Expected: どのファイルにも `get_email_headers` があり、テストは `Failed: 0`

```bash
git add README.md docs src/CalendarMcp.Core/Skills
git commit -m "Document the get_email_headers tool"
git push
```

Expected: fork の CI が成功。fox への反映は、Task 20 の Step 7 と同じ手順でもう一度流す（`Skills/*.md` は `get_guide` が返すので、イメージを作り直す）。二回目は `changed=0`
