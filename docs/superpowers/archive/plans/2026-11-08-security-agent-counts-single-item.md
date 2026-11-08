# ペンテストの件数を origin.rewse.jp に集める Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox と hotel のペンテストの件数を Zabbix のホスト `origin.rewse.jp` の 1 組のアイテムに集め、片方が届かなくても CloudFront の除外後の値を出せるようにする。

**Architecture:** `security-agent-pentest-counts` が `zabbix_sender -T -N` でホストごとに異なるナノ秒を付けて `origin.rewse.jp` に送り、alfa の計算アイテムはそのホストの合計だけを見る。切り替えのあいだは古い送り先にも送り、式を変えてから古い送り先をやめる。

**Tech Stack:** Ansible、bash、Jinja2、Zabbix 7.4.16（`mcporter call zabbix.*`）、Python `unittest`

**Spec:** `docs/superpowers/archive/specs/2026-11-08-security-agent-counts-single-item-design.md`

## Global Constraints

- 作業はワークツリー `.worktrees/security-agent-origin`（ブランチ `security-agent-origin`、main から切る）で行い、プレイブックは `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook ...` で実行する
- 送り先は `httpd_security_agent_zabbix_host: origin.rewse.jp`（`roles/httpd/vars/main.yml`）
- ns は `(inventory_hostname | hash('sha1'))[:7] | int(base=16)`
- 5 分枠の定義（B = now を 300 秒で切り捨てて 600 引く、[B, B+300)）と数え方は変えない
- alfa の計算アイテムの時間シフトは `15m:now-17m` のまま
- ansible-lint はこの Mac の IPv6 の問題で hook が止まるため、`SKIP=ansible-lint` の pre-commit と、hook の環境の `ansible-lint --offline` で代える

## Review Focus

- fox と hotel が同じ枠を同じ時刻で送る: ns が異なり、どちらの値も Zabbix に残る（Task 2 Step 3 で history を見る）
- hotel の agent が止まる: 計算アイテムが supported のまま fox の件数だけで差し引く（Task 2 Step 5 で、hotel の値を除いた手計算と比べる）
- 切り替えの途中でペンテストが走る: 古い式も新しい式も、差し引く件数が欠けない（Task 2 Step 3 の待ち時間、Task 3 の順番）

---

### Task 1: 2 か所に送るスクリプトと conf

**Files:**
- Modify: `roles/httpd/files/security-agent-pentest-counts`
- Delete: `roles/httpd/files/security-agent-pentest-counts.conf`
- Create: `roles/httpd/templates/security-agent-pentest-counts.conf.j2`
- Modify: `roles/httpd/tasks/security_agent.yml`、`roles/httpd/vars/main.yml`
- Modify: `tests/test_security_agent_pentest.py`

**Interfaces:**
- Produces: `security-agent-pentest-counts <log> <zabbix-host> <ns>`。送る行は `- security_agent.requests B ns N`、`- security_agent.errors.5xx B ns E`、`<zabbix-host> security_agent.requests B ns N`、`<zabbix-host> security_agent.errors.5xx B ns E` の 4 行。Task 3 で前の 2 行を消す

- [ ] **Step 1: 失敗するテストを書く**

`run_counts` がスクリプトに `origin.rewse.jp` と `12345` を渡すようにし、既存のテストの期待する行を 4 行に変える。`-N` が引数にあることも確かめる。conf のテストは、テンプレートを描画するテストに置き換える。ヘルパー `render_httpd(name, **variables)` は `tests/test_cloudfront_origin.py` の `render` と同じ環境（`StrictUndefined`、`comment` フィルタ）に、`hash` フィルタ `lambda text, algorithm: hashlib.new(algorithm, text.encode()).hexdigest()` を足して `roles/httpd/templates/` から描画する。

```python
def expected(requests, errors):
    return [
        f"- security_agent.requests {BUCKET} 12345 {requests}",
        f"- security_agent.errors.5xx {BUCKET} 12345 {errors}",
        f"origin.rewse.jp security_agent.requests {BUCKET} 12345 {requests}",
        f"origin.rewse.jp security_agent.errors.5xx {BUCKET} 12345 {errors}",
    ]

# test_sends_requests_and_5xx_for_the_closed_bucket
self.assertIn("-T", sent.args)
self.assertIn("-N", sent.args)
self.assertEqual(sent.input.splitlines(), expected(3, 2))

# test_sends_zero_for_a_quiet_bucket: expected(0, 0)
# test_counts_only_cloudfront_requests: expected(1, 1)
# test_ignores_old_format_lines: expected(1, 0)
# test_reads_rotated_log: expected(2, 2)


class PentestCountsConfTest(unittest.TestCase):
    def conf(self, hostname):
        return render_httpd(
            "security-agent-pentest-counts.conf.j2",
            inventory_hostname=hostname,
            httpd_security_agent_zabbix_host="origin.rewse.jp",
        )

    def test_user_parameter_sends_to_the_origin_host(self):
        line = self.conf("fox.rewse.jp").splitlines()[-1]
        self.assertRegex(
            line,
            r"^UserParameter=security_agent\.sender,/usr/lib/zabbix/agentscripts/"
            r"security-agent-pentest-counts /var/log/apache2/security_agent_pentest\.log "
            r"origin\.rewse\.jp \d+$",
        )

    def test_hosts_get_distinct_nanoseconds(self):
        fox = int(self.conf("fox.rewse.jp").split()[-1])
        hotel = int(self.conf("hotel.rewse.jp").split()[-1])
        self.assertNotEqual(fox, hotel)
        self.assertLess(max(fox, hotel), 1_000_000_000)

    def test_conf_starts_with_ansible_managed(self):
        text = (ROLES / "httpd/templates/security-agent-pentest-counts.conf.j2").read_text()
        self.assertTrue(text.startswith("{{ ansible_managed | comment }}"))
```

`test_user_parameter_runs_the_counter_on_the_pentest_log` は消す。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -q`
Expected: 送る行のテスト 5 件が 2 行と 4 行の違いで FAIL、conf のテスト 3 件がテンプレートがないため FAIL。`test_emits_nothing_when_the_log_is_unreadable` と書式のテスト 3 件は PASS

- [ ] **Step 3: スクリプトとテンプレートを書き換える**

スクリプトは `readonly host=$2 ns=$3` を足し、awk に `-v host=... -v ns=...` を渡して 4 行を出し、`zabbix_sender ... -T -N -i -` に渡す。冒頭のコメントに、fox と hotel が同じ枠を `origin.rewse.jp` に送り ns で区別すること、移行のあいだは自ホストのアイテムにも送ることを書き、Usage を直す。

テンプレートは 1 行目を `{{ ansible_managed | comment }}`、次を UserParameter にし、末尾に `{{ httpd_security_agent_zabbix_host }} {{ (inventory_hostname | hash('sha1'))[:7] | int(base=16) }}` を付ける。`vars/main.yml` に `httpd_security_agent_zabbix_host: origin.rewse.jp` を足し、実体のない Zabbix ホストで fox と hotel の件数を受けることをコメントに書く。`security_agent.yml` の conf のタスクを `ansible.builtin.template`、`src: security-agent-pentest-counts.conf.j2` に変える。古い `files/` の conf は `git rm` する。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q`
Expected: すべて PASS

- [ ] **Step 5: lint**

Run: `git add -A roles/httpd tests && SKIP=ansible-lint uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files && /Users/tats/.cache/pre-commit/repof6n4oo5w/py_env-python3.14/bin/ansible-lint --offline`
Expected: どちらも終了コード 0

- [ ] **Step 6: コミット**

```bash
git commit -m "feat(httpd): send Security Agent pentest counts to origin.rewse.jp"
```

### Task 2: origin.rewse.jp を作って式を切り替える

**Files:** なし（Zabbix API とホストへの適用）

- [ ] **Step 1: ホストとアイテムを作る**

`host_create` で `{"host":"origin.rewse.jp","name":"origin","groups":[{"groupid":"28"}]}` を作り、返った hostid に `item_create` で `Security Agent pentest requests`（`security_agent.requests`）と `Security Agent pentest 5xx responses`（`security_agent.errors.5xx`）を type 2、value_type 3、history `1w`、trends `450d` で作る。`ssh fox 'sudo systemctl restart zabbix-server'` を実行する。
Expected: hostid と itemid が返り、`zabbix-server` が active

- [ ] **Step 2: Task 1 の版を適用する**

`home-primary.yml` と `home-secondary.yml` を `--tags httpd_security_agent` で check のあと適用し、もう一度適用する。
Expected: どれも終了コード 0、2 回目は changed=0

- [ ] **Step 3: 値がたまるのを待つ**

35 分待ち、`history_get` で `origin.rewse.jp` の 2 つのアイテムを見る。
Expected: 3 枠以上で、同じ clock に ns の違う値が 2 つずつ（fox と hotel）あり、枠ごとの合計が fox と hotel の古いアイテムの合計と一致

- [ ] **Step 4: 計算アイテムの式を変える**

`item_update` で itemid 30587、30589、30591 の params の `(sum(/fox.rewse.jp/K,15m:now-17m)+sum(/hotel.rewse.jp/K,15m:now-17m))` を `sum(/origin.rewse.jp/K,15m:now-17m)` に置き換える（K は `security_agent.requests` と `security_agent.errors.5xx`）。`zabbix-server` を再起動する。
Expected: 3 件の itemids が返る

- [ ] **Step 5: 新しい式の値を確かめる**

10 分後に `item_get` で計算アイテム 3 つが state 0 であることを見る。直近の評価の値を、CloudFront の 3 枠から `origin.rewse.jp` の fox の値（hotel の ns の値を除く）を引いた手計算と比べる。hotel の値が 0 なら、hotel を欠いても同じ値になることの確認になる。
Expected: 一致

### Task 3: 古い送り先をやめる

**Files:**
- Modify: `roles/httpd/files/security-agent-pentest-counts`、`tests/test_security_agent_pentest.py`

- [ ] **Step 1: 失敗するテストを書く**

`expected()` を `origin.rewse.jp` の 2 行だけを返すように変える。

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -q`
Expected: 送る行のテスト 5 件が 4 行と 2 行の違いで FAIL

- [ ] **Step 3: awk の `- ...` の 2 行と、移行について書いたコメントを消す**

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests -q`
Expected: すべて PASS

- [ ] **Step 5: コミット**

```bash
git add roles/httpd/files/security-agent-pentest-counts tests/test_security_agent_pentest.py
git commit -m "refactor(httpd): stop sending pentest counts to each origin host"
```

- [ ] **Step 6: 適用して古いアイテムを消す**

`home-primary.yml` と `home-secondary.yml` を `--tags httpd_security_agent` で check のあと適用する。`item_delete` でテンプレート 10228 の `security_agent.requests`（30577）と `security_agent.errors.5xx`（30580）を消し、`zabbix-server` を再起動する。
Expected: 適用の終了コード 0。10 分後に `origin.rewse.jp` に次の枠の値が届き、計算アイテム 3 つが state 0 のまま

- [ ] **Step 7: マージして push する**

main へ `--no-ff` でマージし、同じマージコミットで spec と plan を archive に移し、plan の Spec の行のパスを直す。テストと lint を通して push し、CI を確かめる。
Expected: CI の Lint、Gitleaks、CodeQL が success
