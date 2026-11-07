# calendar-mcp をやめて mailboxd に戻す 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox と各リポジトリから calendar-mcp を取り除き、mailboxd を撤去前の形で `mail-mcp.rewse.jp` に戻す。CloudFront、Route53、UniFi、Security Agent も mail-mcp に戻し、fork を消す。

**Architecture:** ansible-playbooks、cloudfront-waf、security-agent の各リポジトリで、撤去と置き換えのコミットを `git revert` で戻す。ansible-playbooks では続く一つのコミットで `roles/calendar_mcp` を消し、fox からの片づけを `roles/mailboxd/tasks/legacy.yml` に置く。適用は fox、CloudFront、UniFi、Security Agent、fork の削除の順に行う。

**Tech Stack:** Ansible（community.docker 5.2.1）、pytest、CloudFormation、AWS CLI（Route53、Security Agent）、UniFi Site Manager API、gh

**Spec:** `docs/superpowers/specs/2026-11-07-mailboxd-restore-design.md`

## Global Constraints

- mailboxd は撤去前の形に戻す: `mail-mcp.rewse.jp/mcp`、ポート 8083、メールボックスは ts、ubiqu、kyn の 3 つ、1Password の mailboxd 項目は `7tbut3qmtfp7dettl6hqsh6tei`、`pjplhxwrdrm25hob63i37iqdkm`、`b7wlevkrmcvdmd5x27wdzfgewu`（ID は撤去前と同じ）
- revert のコミットメッセージは `git revert` の既定（`Revert "<元の件名>"` と `This reverts commit <sha>.`）を使う。ansible-playbooks の先例（`7f90d866` など）に合わせる
- Route53 のホストゾーンは `Z34LVKL0P9KD74`。既定の AWS プロファイル（Route53FullAccess を持つ）で書く
- トークンやパスワードを端末やログに出さない。比べるときは `shasum -a 256` の先頭だけを出す。curl に渡すときは `-H @-` で標準入力から読ませる
- トークンなしの 401 は fail2ban が数える。トークンなしの確認は家から 1 回、CloudFront 経由で 1 回までにする
- ansible-playbook は同時に二つ走らせない。fox への適用の前に `git -P fetch && git -P log --oneline HEAD..origin/main` が空であることを確かめる
- ansible-playbooks のテスト: `uv run --with pytest --with ansible-core pytest tests -q`、リント: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`（新規ファイルは先に `git add`）
- cloudfront-waf の確認: `uv run pytest -q`、`uv run cfn-lint infra/deploy-role.yaml infra/template.yaml`、同じ pre-commit。security-agent の確認: `uv run pytest -q`、同じ pre-commit
- コミット前に `git -P status -sb` でブランチが `main` であることを確かめる。ansible-playbooks の root clone を別のセッションが切り替えていたら、`.worktrees/<name>` の worktree で続ける

## Review Focus

- mailboxd のイメージ: `aged_release` が撤去前と同じ v0.8.0 を選ぶ。違うタグになったら、適用前に CHANGELOG で設定の変更を確かめる（Task 3 Step 3）
- calendar-mcp の Compose ファイルがもうないホスト（2 回目の実行）: legacy は compose を飛ばし、ほかのタスクも `ok` になって `changed=0`（Task 3 Step 7）
- 消えた `calendar-mcp` アカウント: ファイルを消したあとにユーザー、グループの順で消すので、所有者のないファイルが残らない（Task 3 Step 5）
- Security Agent の作り直した mail-mcp の target domain: 未確認のまま pentest を作ると deploy が失敗するかもしれない。失敗したら一度 `HomeTargetDomainsVerified=false` で deploy し、確認してから `true` に戻す（Task 6 Step 4）
- fork の削除: `gh` のトークンに `delete_repo` スコープがない。足りないときは利用者に `gh auth refresh -h github.com -s delete_repo` を頼む（Task 7 Step 2）

---

### Task 1: ansible-playbooks で mailboxd の撤去を revert する

**Files:**
- Restore: `roles/mailboxd/**`、`tests/test_mailboxd.py`
- Modify: `home-primary.yml`、`tests/test_fail2ban_apache.py`、`roles/calendar_mcp/tasks/main.yml`
- Delete: `roles/calendar_mcp/tasks/legacy.yml`
- Resolve: `tests/test_calendar_mcp.py`

**Interfaces:**
- Produces: `roles/mailboxd`（撤去前と同じ、`tasks/main.yml` は config、container、apache、fail2ban の 4 つを import）、`tests/test_mailboxd.py` の `ROLE`、`task_named`、`main_imports`

- [ ] **Step 1: revert を始める**

Run: `git -P revert --no-commit a0aac483`
Expected: `CONFLICT (content): Merge conflict in tests/test_calendar_mcp.py` だけが出る

- [ ] **Step 2: `tests/test_calendar_mcp.py` の衝突を解く**

`git -P checkout --ours tests/test_calendar_mcp.py` でいまの形にしてから、`CalendarMcpLegacyTest` クラスを丸ごと消し、`test_components_are_imported_in_order` の期待値から `"legacy.yml"` を消す。`git add tests/test_calendar_mcp.py`。

- [ ] **Step 3: テストとリントを通す**

Run: テストとリント（Global Constraints のコマンド）
Expected: テストは全件 PASS（`tests/test_mailboxd.py` が戻り、`CalendarMcpLegacyTest` の 2 件が減る）、リントはすべて Passed か Skipped

- [ ] **Step 4: コミット**

```bash
git -P status -sb
git -c core.editor=true revert --continue
git -P log -1 --format='%h %s' | cat
```

Expected: 件名が `Revert "feat(mailboxd)!: retire mailboxd in favor of calendar_mcp"`

---

### Task 2: calendar_mcp ロールを消し、fox からの片づけを mailboxd に置く

**Files:**
- Create: `roles/mailboxd/tasks/legacy.yml`
- Modify: `roles/mailboxd/tasks/main.yml`（最後に import）、`home-primary.yml`（calendar_mcp の行を消す）、`tests/test_fail2ban_apache.py`（`"calendar_mcp"` を消す）、`tests/test_mailboxd.py`
- Delete: `roles/calendar_mcp/`、`tests/test_calendar_mcp.py`

**Interfaces:**
- Consumes: Task 1 の `roles/mailboxd` と `tests/test_mailboxd.py` の `ROLE`、`main_imports`
- Produces: タスク名 `legacy | Check calendar-mcp compose file`（register `__mailboxd_calendar_mcp_compose`）、`legacy | Stop calendar-mcp`、`legacy | Remove .NET base images`、`legacy | Remove calendar-mcp vhost`、`legacy | Remove calendar-mcp fail2ban jail`、`legacy | Remove calendar-mcp files`、`legacy | Remove calendar-mcp user`、`legacy | Remove calendar-mcp group`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_mailboxd.py` の末尾に足す。

```python
class MailboxdLegacyTest(unittest.TestCase):
    @staticmethod
    def tasks() -> list:
        return yaml.safe_load((ROLE / "tasks" / "legacy.yml").read_text())

    @staticmethod
    def removed_paths(tasks):
        for t in tasks:
            module = t.get("ansible.builtin.file")
            if module:
                yield from (
                    t["loop"] if module["path"] == "{{ item }}" else [module["path"]]
                )

    def test_removes_only_calendar_mcp_state(self):
        tasks = self.tasks()
        self.assertEqual(
            sorted(self.removed_paths(tasks)),
            [
                "/etc/apache2/sites-available/calendar-mcp.rewse.jp.conf",
                "/etc/apache2/sites-enabled/calendar-mcp.rewse.jp.conf",
                "/etc/compose/calendar_mcp",
                "/etc/fail2ban/filter.d/calendar_mcp.conf",
                "/etc/fail2ban/jail.d/calendar_mcp.conf",
                "/srv/calendar_mcp",
                "/usr/local/src/calendar-mcp",
            ],
        )
        for t in tasks:
            if "ansible.builtin.file" in t:
                self.assertEqual(t["ansible.builtin.file"]["state"], "absent")

    def test_stops_calendar_mcp_only_while_its_compose_file_exists(self):
        tasks = self.tasks()
        stat = next(t for t in tasks if "ansible.builtin.stat" in t)
        down = next(t for t in tasks if "community.docker.docker_compose_v2" in t)
        self.assertEqual(
            stat["ansible.builtin.stat"]["path"],
            "/etc/compose/calendar_mcp/compose.yaml",
        )
        args = down["community.docker.docker_compose_v2"]
        self.assertEqual(args["project_src"], "/etc/compose/calendar_mcp")
        self.assertEqual(args["state"], "absent")
        self.assertEqual(args["remove_images"], "all")
        self.assertIn(stat["register"], down["when"])
        self.assertLess(
            tasks.index(down),
            min(i for i, t in enumerate(tasks) if "ansible.builtin.file" in t),
        )

    def test_removes_the_dotnet_base_images(self):
        task = next(
            t for t in self.tasks() if "community.docker.docker_image_remove" in t
        )
        self.assertEqual(
            task["community.docker.docker_image_remove"]["name"], "{{ item }}"
        )
        self.assertEqual(
            sorted(task["loop"]),
            ["mcr.microsoft.com/dotnet/aspnet:10.0", "mcr.microsoft.com/dotnet/sdk:10.0"],
        )

    def test_removes_the_account_after_its_files(self):
        tasks = self.tasks()
        user = next(t for t in tasks if "ansible.builtin.user" in t)
        group = next(t for t in tasks if "ansible.builtin.group" in t)
        self.assertEqual(user["ansible.builtin.user"]["name"], "calendar-mcp")
        self.assertEqual(user["ansible.builtin.user"]["state"], "absent")
        self.assertEqual(group["ansible.builtin.group"]["name"], "calendar-mcp")
        self.assertEqual(group["ansible.builtin.group"]["state"], "absent")
        last_file = max(i for i, t in enumerate(tasks) if "ansible.builtin.file" in t)
        self.assertLess(last_file, tasks.index(user))
        self.assertLess(tasks.index(user), tasks.index(group))

    def test_legacy_is_imported_last(self):
        imports = main_imports()
        self.assertEqual(list(imports)[-1], "legacy.yml")
        self.assertEqual(imports["legacy.yml"], ["mailboxd_legacy"])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_mailboxd.py -q -k Legacy`
Expected: 4 件が `FileNotFoundError`（`legacy.yml` がない）、`test_legacy_is_imported_last` が `'fail2ban.yml' != 'legacy.yml'` で失敗する

- [ ] **Step 3: `roles/mailboxd/tasks/legacy.yml` を作る**

`git -P show a0aac483:roles/calendar_mcp/tasks/legacy.yml` と同じ形で、対象を calendar-mcp にする。冒頭の英語のコメントは、mailboxd が calendar_mcp を置き換えたこと、全ホストが収束したらこのファイルと import を消すことを書く。タスクは Interfaces の名前でこの順に置く。

- `legacy | Check calendar-mcp compose file`: `/etc/compose/calendar_mcp/compose.yaml` を stat し、`__mailboxd_calendar_mcp_compose` に register
- `legacy | Stop calendar-mcp`: `project_src: /etc/compose/calendar_mcp`、`state: absent`、`remove_images: all`、`when: __mailboxd_calendar_mcp_compose.stat.exists`
- `legacy | Remove .NET base images`: `community.docker.docker_image_remove` の `name: "{{ item }}"` を二つのイメージで loop
- `legacy | Remove calendar-mcp vhost`: `sites-enabled` と `sites-available` の `calendar-mcp.rewse.jp.conf`、`notify: Reload Apache`
- `legacy | Remove calendar-mcp fail2ban jail`: `filter.d/calendar_mcp.conf` と `jail.d/calendar_mcp.conf`、`notify: Restart fail2ban`
- `legacy | Remove calendar-mcp files`: `/etc/compose/calendar_mcp`、`/srv/calendar_mcp`、`/usr/local/src/calendar-mcp`
- `legacy | Remove calendar-mcp user`: `ansible.builtin.user` の `name: calendar-mcp`、`state: absent`
- `legacy | Remove calendar-mcp group`: `ansible.builtin.group` の `name: calendar-mcp`、`state: absent`

- [ ] **Step 4: `roles/mailboxd/tasks/main.yml` の最後に import を足す**

```yaml
- name: Import legacy tasks
  ansible.builtin.import_tasks: legacy.yml
  tags:
    - mailboxd_legacy
```

- [ ] **Step 5: テストを通す**

Run: `uv run --with pytest --with ansible-core pytest tests/test_mailboxd.py -q -k Legacy`
Expected: 5 passed

- [ ] **Step 6: calendar_mcp を消す**

`git rm -r -q roles/calendar_mcp tests/test_calendar_mcp.py`。`home-primary.yml` から `calendar_mcp` のロールの 3 行を、`tests/test_fail2ban_apache.py` の一覧から `"calendar_mcp",` を消す。

- [ ] **Step 7: 残りの参照がないことを確かめる**

Run: `rg -n -i "calendar.mcp" --hidden -g '!.git' -g '!docs/superpowers/**' -g '!roles/mailboxd/tasks/legacy.yml' -g '!tests/test_mailboxd.py' .`
Expected: 何も出ない

- [ ] **Step 8: テストとリントを通す**

Run: テストとリント（Global Constraints のコマンド）
Expected: テストは全件 PASS、リントはすべて Passed か Skipped

- [ ] **Step 9: コミット**

```bash
git -P status -sb
git add roles/mailboxd/tasks/legacy.yml roles/mailboxd/tasks/main.yml home-primary.yml tests/test_fail2ban_apache.py tests/test_mailboxd.py
git commit -m "feat(calendar_mcp)!: remove calendar_mcp in favor of mailboxd" -m "Muse reads the iCloud calendars and contacts through its device access, so calendar-mcp served only mail, which mailboxd already covers. The mailboxd legacy component stops the calendar-mcp containers, removes their images and the .NET base images, and deletes the vhost, fail2ban jail, configuration, data, source checkout, and the calendar-mcp account on fox." -m "BREAKING CHANGE: calendar-mcp.rewse.jp and the calendar_mcp role are gone; Muse uses mail-mcp.rewse.jp/mcp again."
git -P log -1 --oneline | cat
```

---

### Task 3: fox に適用して確かめ、ansible-playbooks を push する

**Files:** なし（適用と確認だけ）

**Interfaces:**
- Consumes: Task 1 と Task 2 のコミット

- [ ] **Step 1: origin と揃っていることを確かめる**

Run: `git -P fetch && git -P log --oneline HEAD..origin/main`
Expected: 何も出ない

- [ ] **Step 2: check で差分を見る**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags mailboxd --check --diff`
Expected: `failed=0`。mailboxd の設定、Compose、vhost、fail2ban が作られ、legacy の各タスクが calendar-mcp を消す差分を出す

- [ ] **Step 3: イメージのタグを確かめる**

Step 2 の出力で `container | Deploy compose file` の差分にある mailboxd のイメージのタグを見る。
Expected: `psyb0t/mailbox:v0.8.0@sha256:...`。違うタグなら、適用する前に docker-mailbox の CHANGELOG で設定の変更を確かめ、ledger に記録する

- [ ] **Step 4: 適用する**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags mailboxd`
Expected: 終了コード 0、`failed=0`

- [ ] **Step 5: fox の状態を確かめる**

Run: `ssh fox.rewse.jp 'docker ps --format "{{.Names}} {{.Status}}"; docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "calendar|dotnet|mailbox"; ls -d /etc/compose/calendar_mcp /srv/calendar_mcp /usr/local/src/calendar-mcp /etc/apache2/sites-enabled/calendar-mcp.rewse.jp.conf /etc/fail2ban/jail.d/calendar_mcp.conf 2>&1 | grep -vc "No such file"; getent passwd calendar-mcp; getent group calendar-mcp; sudo fail2ban-client status | grep -o "mailboxd\|calendar_mcp"'`
Expected: `mailboxd` が `(healthy)` で、calendar-mcp のコンテナがない。イメージは `psyb0t/mailbox` だけ。`ls` で残ったパスは 0。`getent` は何も出さない。fail2ban のジェイルは `mailboxd` だけ

- [ ] **Step 6: mail-mcp を家から確かめる**

Run: `curl -s -o /dev/null -w "%{http_code}\n" --resolve mail-mcp.rewse.jp:443:192.168.0.30 https://mail-mcp.rewse.jp/health; curl -s -o /dev/null -w "%{http_code}\n" --resolve mail-mcp.rewse.jp:443:192.168.0.30 -X POST https://mail-mcp.rewse.jp/mcp`
続けて、ts のトークンで `initialize` を送る。

```bash
direnv exec /Volumes/ExternalHD/git/ansible-playbooks op read "op://ansible/7tbut3qmtfp7dettl6hqsh6tei/credential" \
  | sed 's/^/Authorization: Bearer /' \
  | curl -s -o /dev/null -w "%{http_code}\n" --resolve mail-mcp.rewse.jp:443:192.168.0.30 \
      -H @- -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
      -X POST https://mail-mcp.rewse.jp/mcp \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
```

Expected: `/health` が 200、トークンなしが 401、トークンありの `initialize` が 200

- [ ] **Step 7: 2 回目の適用で変更がないことを確かめる**

Run: `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags mailboxd`
Expected: `changed=0`、`failed=0`

- [ ] **Step 8: push する**

```bash
git -P status -sb
git push origin main
```

Expected: spec、plan、Task 1、Task 2 のコミットが origin/main に載り、CI（Gitleaks、Lint、Push on main）が成功する

---

### Task 4: cloudfront-waf を mail-mcp に戻す

**Files:**（`/Volumes/ExternalHD/git/cloudfront-waf`）
- Modify by revert: `README.md`、`docs/setup.md`、`infra/template.yaml`、`scripts/switch-dns.sh`、`tests/test_switch_dns.py`、`tests/test_template.py`

**Interfaces:**
- Consumes: Task 3 で fox が `mail-mcp.rewse.jp` を返していること

- [ ] **Step 1: 最新にする**

Run: `git -P pull --ff-only && git -P status -sb`
Expected: `## main...origin/main`、変更なし

- [ ] **Step 2: 二つのコミットを revert する**

Run: `git -c core.editor=true revert b105d44 8e6520c && git -P log --oneline -3 | cat`
Expected: 衝突なしで `Revert "feat!: stop serving mail-mcp.rewse.jp"` と `Revert "feat: serve calendar-mcp.rewse.jp through CloudFront"` の二つのコミットができる

- [ ] **Step 3: 確かめる**

Run: `rg -n "calendar-mcp" -g '!docs/superpowers/**' . ; uv run pytest -q; uv run cfn-lint infra/deploy-role.yaml infra/template.yaml; uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: `rg` は何も出さず、テストは全件 PASS、cfn-lint は出力なし、pre-commit はすべて Passed か Skipped

- [ ] **Step 4: deploy して DNS を切り替える**

Run: `AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` に続けて `AWS_PROFILE=cloudfront-waf-deploy scripts/switch-dns.sh cloudfront`
Expected: どちらも終了コード 0。スタックが `UPDATE_COMPLETE` になり、Route53 の変更が `INSYNC` になる

- [ ] **Step 5: calendar-mcp の CNAME を消す**

`aws route53 list-resource-record-sets --hosted-zone-id Z34LVKL0P9KD74 --query "ResourceRecordSets[?Name=='calendar-mcp.rewse.jp.']" | cat` で今の値を読み、その値をそのまま `DELETE` の change batch に入れて `aws route53 change-resource-record-sets --hosted-zone-id Z34LVKL0P9KD74` で消す。
Expected: 変更が `INSYNC` になり、同じ list が `[]` を返す

- [ ] **Step 6: CloudFront 経由で確かめる**

Run: `dig +short mail-mcp.rewse.jp @1.1.1.1 | head -2; dig +short calendar-mcp.rewse.jp @1.1.1.1; curl -s -o /dev/null -w "%{http_code}\n" https://mail-mcp.rewse.jp/health; curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mail-mcp.rewse.jp/mcp`
Expected: mail-mcp は CloudFront の名前に解決し、calendar-mcp は何も返さない。`/health` が 200、トークンなしの `/mcp` が 401（家のネットワークでも UniFi の切り替え前は CloudFront を通る）

- [ ] **Step 7: push する**

Run: `git -P status -sb && git push origin main`
Expected: CI（Gitleaks、Lint、Test）が成功する

---

### Task 5: UniFi の DNS ポリシーを入れ替える

**Files:** なし（UniFi の設定）

**Interfaces:**
- Consumes: なし（API キーは `op://ansible/bvdayezevkxx6kmhjc3kmug7u4/credential`、コンソール名は `sierra`）

- [ ] **Step 1: サイトとポリシーを読む**

`https://api.ui.com/ea/hosts` から `reportedState.name` が `sierra` のコンソール ID を、`https://api.ui.com/v1/connector/consoles/<console>/proxy/network/integration/v1/sites` からサイト ID を読み、`.../sites/<site>/dns/policies` を GET する。キーは `op read` から `X-API-KEY: ` を付けて `-H @-` で渡す。
Expected: `calendar-mcp.rewse.jp` の CNAME ポリシー `fb57fc89-e4bd-486f-9098-b788753e7fc7` があり、`mail-mcp.rewse.jp` のポリシーはない

- [ ] **Step 2: mail-mcp のポリシーを作る**

Step 1 の calendar-mcp のポリシーの本文から `id` と `metadata` を除き、`domain` を `mail-mcp.rewse.jp` に変えて同じ一覧に POST する。`ttlSeconds` は `0`、向け先は `fox.rewse.jp`。
Expected: 201 か 200 で、新しいポリシーの `domain` が `mail-mcp.rewse.jp`

- [ ] **Step 3: calendar-mcp のポリシーを消す**

`.../dns/policies/fb57fc89-e4bd-486f-9098-b788753e7fc7` に DELETE を送る。
Expected: 200 か 204

- [ ] **Step 4: 家の DNS で確かめる**

Run: `dig +short mail-mcp.rewse.jp @192.168.0.1; dig +short calendar-mcp.rewse.jp @192.168.0.1`
Expected: mail-mcp は `fox.rewse.jp.` とその家のアドレスを返し、calendar-mcp は何も返さない

---

### Task 6: security-agent の pentest を mail-mcp に戻す

**Files:**（`/Volumes/ExternalHD/git/security-agent`）
- Modify by revert: `docs/setup.md`、`infra/template.yaml`、`targets.toml`、`tests/test_config.py`、`tests/test_infra.py`

**Interfaces:**
- Consumes: Task 4 で `mail-mcp.rewse.jp` がインターネットから届くこと

- [ ] **Step 1: 最新にする**

Run: `git -P pull --ff-only && git -P status -sb`
Expected: `## main...origin/main`、変更なし

- [ ] **Step 2: 二つのコミットを revert する**

Run: `git -c core.editor=true revert a53977d 3fb6e6a && git -P log --oneline -3 | cat`
Expected: 衝突なしで `Revert "feat!: stop the mail-mcp.rewse.jp pentest"` と `Revert "feat: add a monthly pentest for calendar-mcp.rewse.jp"` の二つのコミットができる

- [ ] **Step 3: 確かめる**

Run: `rg -n "calendar-mcp" -g '!docs/superpowers/**' . ; uv run pytest -q; uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files`
Expected: `rg` は何も出さず、テストは全件 PASS、pre-commit はすべて Passed か Skipped。`infra/template.yaml` の mail-mcp の schedule は `cron(15 21 26 * ? *)`

- [ ] **Step 4: deploy する**

Run: `AWS_PROFILE=security-agent-deploy aws cloudformation deploy --region us-east-1 --stack-name security-agent --template-file infra/template.yaml --capabilities CAPABILITY_NAMED_IAM` に続けて `AWS_PROFILE=security-agent-deploy infra/scripts/configure-pr-review.sh`（パラメーターは前の値のまま）
Expected: スタックが `UPDATE_COMPLETE`。未確認の target domain のせいで pentest の作成が失敗したら、`--parameter-overrides HomeTargetDomainsVerified=false` で deploy し直し、Step 5 のあとで `true` に戻して deploy し、そのたびに `configure-pr-review.sh` を実行する。この分岐を通ったら ledger に記録する

- [ ] **Step 5: mail-mcp の target domain を確認する**

`aws securityagent list-target-domains --region us-east-1` で `mail-mcp.rewse.jp` の ID を読み、`batch-get-target-domains` で TXT の名前と値を読む。`_aws_securityagent-challenge.mail-mcp.rewse.jp` の TXT を Route53 に UPSERT し、`aws securityagent verify-target-domain`（なければコンソールの **Verify**）で確認する。
Expected: `batch-get-target-domains` の状態が `VERIFIED`

- [ ] **Step 6: calendar-mcp の TXT を消す**

`_aws_securityagent-challenge.calendar-mcp.rewse.jp` の TXT を今の値で `DELETE` する。
Expected: `list-resource-record-sets` に `calendar-mcp` を含む名前が一つもない。`list-target-domains` に `calendar-mcp.rewse.jp` がない

- [ ] **Step 7: push する**

Run: `git -P status -sb && git push origin main`
Expected: CI（Gitleaks、Lint、Test）が成功する

---

### Task 7: fork を消して仕上げる

**Files:**
- Move: `docs/superpowers/specs/2026-11-07-mailboxd-restore-design.md` → `docs/superpowers/archive/specs/`、`docs/superpowers/plans/2026-11-07-mailboxd-restore.md` → `docs/superpowers/archive/plans/`（ansible-playbooks）

**Interfaces:**
- Consumes: Task 3 で fox が fork を参照しなくなったこと

- [ ] **Step 1: ローカルの clone に残す作業がないことを確かめる**

Run: `cd /Volumes/ExternalHD/git/calendar-mcp && git -P status --porcelain | cat && git -P log --branches --not --remotes --oneline | cat`
Expected: どちらも何も出ない

- [ ] **Step 2: GitHub の fork を消す**

Run: `gh repo delete rewse/calendar-mcp --yes`
Expected: 終了コード 0。`delete_repo` スコープがないと言われたら、利用者に `gh auth refresh -h github.com -s delete_repo` を頼んでから同じコマンドを実行する

- [ ] **Step 3: ローカルの clone を消す**

Run: `command rm -rf /Volumes/ExternalHD/git/calendar-mcp && ls /Volumes/ExternalHD/git | grep -c calendar-mcp`
Expected: `0`

- [ ] **Step 4: spec と plan を archive に移して push する**

`git mv` で二つを archive に移し、plan の `**Spec:**` を `docs/superpowers/archive/specs/2026-11-07-mailboxd-restore-design.md` に直す。

```bash
git -P status -sb
git add docs/superpowers/archive/plans/2026-11-07-mailboxd-restore.md
git commit -m "docs: archive the mailboxd restore spec and plan"
git push origin main
```

Expected: CI が成功する
