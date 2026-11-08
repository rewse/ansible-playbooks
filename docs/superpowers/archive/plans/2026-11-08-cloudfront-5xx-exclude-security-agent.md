# CloudFront 5xx 率から AWS Security Agent のペンテストを除く Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CloudFront の 5xx アラートを、AWS Security Agent のペンテストのリクエストを除いた 5xx 率で判定する。

**Architecture:** fox と hotel の Apache がペンテストのリクエストを応答コードと CloudFront 経由かどうかつきで `security_agent_pentest.log` に書き、新しいスクリプトが閉じた 5 分枠ごとに件数を Zabbix へ送る。alfa の `cloudfront_waf.sh` は同じ枠の CloudFront のリクエスト数と 5xx 数を送る。Zabbix の計算アイテムが過去の 3 枠を合計して差し引き、既存のトリガーをその率で判定する式に置き換える。

**Tech Stack:** Ansible、Apache httpd 2.4、bash、AWS CLI（CloudWatch `get-metric-data`）、Zabbix 7.4.16（trapper、計算アイテム、`mcporter call zabbix.*`）、Python `unittest`

**Spec:** `docs/superpowers/archive/specs/2026-11-08-cloudfront-5xx-exclude-security-agent-design.md`

## Global Constraints

- 作業はワークツリー `.worktrees/cloudfront-5xx-security-agent`（ブランチ `cloudfront-5xx-security-agent`、main から切る）で行う。プレイブックは `direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook ...` で実行する
- ペンテストの識別は秘密ヘッダーで立つ `security_agent_pentest` で行い、User-Agent は使わない
- 数えるのは 4 列目（`%{cloudfront_origin}e`）が `1` の行だけ。列が 4 つない行は数えない
- 5 分枠の開始 B は `now` を 300 秒で切り捨てた値から 600 を引いたもの。枠は [B, B+300)。値は `zabbix_sender -T` で時刻 B として送る
- 既存の trapper キー（`cloudfront.requests`、`cloudfront.error_rate.5xx` など）と、それを送る処理は変えない
- 除外後の値が負になったら 0 で止める
- 除外後の判定はリクエスト数 50 以上を条件にする。除外後のアイテムに 30 分値がないときは、今のトリガー式（リクエスト数 30 以上）で判定する
- AGENTS.md の Ansible 規約（タスク名の接頭辞、`mode` の書き方、`changed_when`、check mode で変更しない、2 回目の実行で `changed=0`）に従う
- コードのコメントとコミットメッセージは英語、Conventional Commits

## Review Focus

- 日付が変わった直後（00:00 から 00:10）: 枠の行はローテーションで `security_agent_pentest.log.1` にある。スクリプトは `.1` も読んで同じ件数を出す（Task 2 のテスト `test_reads_rotated_log`）
- 書式変更前の 2 列の行が残っている: 数えずに無視し、エラーにしない（Task 2 のテスト `test_ignores_old_format_lines`）
- origin に直接来たペンテストのリクエスト（4 列目が `-`）: 数えない（Task 2 のテスト `test_counts_only_cloudfront_requests`）
- CloudWatch に枠のデータがない: 何も送らず、0 という偽の値を送らない（Task 3 のテスト `test_sends_nothing_without_bucket_data`）
- fail2ban の ignore スクリプトが新しい 4 列の行でも同じアドレスを見つける（Task 1 のテスト `test_fail2ban_ignore_reads_four_column_lines`）

---

### Task 1: ペンテストのログ書式

**Files:**
- Modify: `roles/httpd/templates/security-agent-pentest.conf.j2`
- Modify: `roles/teslamate/templates/grafana.rewse.jp.conf.j2:20-28`
- Create: `tests/test_security_agent_pentest.py`

**Interfaces:**
- Produces: Apache の `LogFormat` の名前 `security_agent_pentest`、書式 `%{sec}t %a %>s %{cloudfront_origin}e`。Task 2 がこの 4 列を読む

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_security_agent_pentest.py` を作り、`ROLES = pathlib.Path(__file__).resolve().parents[1] / "roles"` を置く。

```python
LOG_FORMAT = 'LogFormat "%{sec}t %a %>s %{cloudfront_origin}e" security_agent_pentest'
CUSTOM_LOG = (
    "CustomLog ${APACHE_LOG_DIR}/security_agent_pentest.log "
    "security_agent_pentest env=security_agent_pentest"
)


class PentestLogFormatTest(unittest.TestCase):
    def test_server_config_defines_the_format(self):
        text = (ROLES / "httpd/templates/security-agent-pentest.conf.j2").read_text()
        self.assertIn(LOG_FORMAT, text)
        self.assertIn(CUSTOM_LOG, text)

    def test_grafana_vhost_uses_the_shared_format(self):
        text = (ROLES / "teslamate/templates/grafana.rewse.jp.conf.j2").read_text()
        self.assertIn(CUSTOM_LOG, text)
        self.assertNotIn('security_agent_pentest.log "', text)

    def test_fail2ban_ignore_reads_four_column_lines(self):
        script = ROLES / "httpd/files/fail2ban-ignore-security-agent"
        now = int(time.time())
        with tempfile.NamedTemporaryFile("w", suffix=".log") as log:
            log.write(f"{now} 192.0.2.10 500 1\n")
            log.flush()
            hit = subprocess.run(["sh", str(script), "192.0.2.10", log.name], check=False)
            miss = subprocess.run(["sh", str(script), "192.0.2.11", log.name], check=False)
        self.assertEqual(hit.returncode, 0)
        self.assertEqual(miss.returncode, 1)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -v`
Expected: `test_server_config_defines_the_format` と `test_grafana_vhost_uses_the_shared_format` が AssertionError で FAIL。`test_fail2ban_ignore_reads_four_column_lines` は既存の動作を固定するテストなので PASS

- [ ] **Step 3: 書式を変える**

`security-agent-pentest.conf.j2` で `CustomLog` の直前に `LOG_FORMAT` の行を置き、`CustomLog` を `CUSTOM_LOG` の行にする。コメントの「The log holds only the time and the address.」を、時刻、アドレス、応答コード、`cloudfront_origin`（CloudFront 経由なら `1`）を書くこと、Zabbix の件数がこの列を読むこと、`grafana.rewse.jp` の vhost が同じ名前を使うことに書き換える。`grafana.rewse.jp.conf.j2` の 28 行目を `CUSTOM_LOG` の行にし、23 行目付近のコメントに書式を httpd ロールの名前から取ることを書く。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -v`
Expected: 3 件 PASS

- [ ] **Step 5: コミット**

```bash
git add roles/httpd/templates/security-agent-pentest.conf.j2 roles/teslamate/templates/grafana.rewse.jp.conf.j2 tests/test_security_agent_pentest.py
git commit -m "feat(httpd): log status and CloudFront origin for pentest requests"
```

### Task 2: ペンテストの件数を送るスクリプト

**Files:**
- Create: `roles/httpd/files/security-agent-pentest-counts`
- Create: `roles/httpd/files/security-agent-pentest-counts.conf`
- Modify: `roles/httpd/tasks/security_agent.yml`
- Modify: `tests/test_security_agent_pentest.py`

**Interfaces:**
- Consumes: Task 1 の 4 列の書式
- Produces: UserParameter `security_agent.sender`。trapper キー `security_agent.requests` と `security_agent.errors.5xx`（整数、時刻 B）。Task 5 がこのキーでアイテムを作る

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_security_agent_pentest.py` にヘルパー `run_counts(lines, rotated_lines=(), log_exists=True)` とテストを足す。ヘルパーは一時ディレクトリに `security_agent_pentest.log`（`rotated_lines` があれば `.1` も）を書き、`+%s` に `NOW` を返す偽の `date` と、引数と標準入力を記録する偽の `zabbix_sender` を PATH の先頭に置いて、`bash roles/httpd/files/security-agent-pentest-counts <log>` を動かす。`log_exists=False` ならログを作らずに同じパスを渡す。戻り値は標準出力と、`zabbix_sender` の呼び出し（`args` と `input`、呼ばれなければ `None`）。

```python
NOW = 1794092400 + 700  # 2026-11-08 08:11:40 JST, inside a bucket
BUCKET = (NOW // 300) * 300 - 600


class PentestCountsTest(unittest.TestCase):
    def test_sends_requests_and_5xx_for_the_closed_bucket(self):
        stdout, sent = run_counts([
            f"{BUCKET} 192.0.2.10 200 1",
            f"{BUCKET + 10} 192.0.2.10 500 1",
            f"{BUCKET + 299} 192.0.2.10 502 1",
            f"{BUCKET - 1} 192.0.2.10 500 1",
            f"{BUCKET + 300} 192.0.2.10 500 1",
        ])
        self.assertIn("-T", sent.args)
        self.assertEqual(
            sent.input.splitlines(),
            [f"- security_agent.requests {BUCKET} 3", f"- security_agent.errors.5xx {BUCKET} 2"],
        )
        self.assertEqual(stdout.strip(), "0")

    def test_sends_zero_for_a_quiet_bucket(self):
        _, sent = run_counts([])
        self.assertEqual(
            sent.input.splitlines(),
            [f"- security_agent.requests {BUCKET} 0", f"- security_agent.errors.5xx {BUCKET} 0"],
        )

    def test_counts_only_cloudfront_requests(self):
        _, sent = run_counts([f"{BUCKET} 192.0.2.10 500 -", f"{BUCKET} 192.0.2.10 500 1"])
        self.assertIn(f"- security_agent.requests {BUCKET} 1", sent.input)
        self.assertIn(f"- security_agent.errors.5xx {BUCKET} 1", sent.input)

    def test_ignores_old_format_lines(self):
        _, sent = run_counts([f"{BUCKET} 192.0.2.10", f"{BUCKET} 192.0.2.10 404 1"])
        self.assertIn(f"- security_agent.requests {BUCKET} 1", sent.input)
        self.assertIn(f"- security_agent.errors.5xx {BUCKET} 0", sent.input)

    def test_reads_rotated_log(self):
        _, sent = run_counts(
            [f"{BUCKET + 5} 192.0.2.10 500 1"], rotated_lines=[f"{BUCKET} 192.0.2.10 500 1"]
        )
        self.assertIn(f"- security_agent.requests {BUCKET} 2", sent.input)

    def test_emits_nothing_when_the_log_is_unreadable(self):
        stdout, sent = run_counts([], log_exists=False)
        self.assertEqual(stdout, "")
        self.assertIsNone(sent)

    def test_user_parameter_runs_the_counter_on_the_pentest_log(self):
        text = (ROLES / "httpd/files/security-agent-pentest-counts.conf").read_text()
        self.assertEqual(
            text.strip(),
            "UserParameter=security_agent.sender,/usr/lib/zabbix/agentscripts/"
            "security-agent-pentest-counts /var/log/apache2/security_agent_pentest.log",
        )
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -v -k PentestCounts`
Expected: スクリプトと conf がないため、7 件が FileNotFoundError か AssertionError で FAIL

- [ ] **Step 3: `security-agent-pentest-counts <log>` を実装する**

bash で書く。`<log>` が読めなければ何も出さずに 1 で終わる。B を `$(( $(date +%s) / 300 * 300 - 600 ))` で出し、読める `<log>.1` と `<log>` を awk に渡して `NF >= 4 && $4 == "1" && $1 >= B && $1 < B + 300` の行を数え、`$3 ~ /^5/` を 5xx とする。2 行を `zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -T -i -` に渡して出力は捨て、`zabbix_sender` の終了コードを標準出力に書く。先頭のコメントに、枠の定義と、alfa の `cloudfront_waf.sh` が同じ枠で送ることを書く。conf はテストの 1 行だけにする。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_security_agent_pentest.py -v`
Expected: 10 件 PASS

- [ ] **Step 5: タスクを足す**

`roles/httpd/tasks/security_agent.yml` の末尾に、`roles/httpd/tasks/remoteip_drift.yml` と同じ形の 3 タスクを足す。`security_agent | Create agentscripts directory`、`security_agent | Copy pentest count script`（`/usr/lib/zabbix/agentscripts/security-agent-pentest-counts`、`"0755"`）、`security_agent | Copy pentest count agent config`（`/etc/zabbix/zabbix_agentd.d/security-agent-pentest-counts.conf`、`"0644"`、`notify: Restart zabbix-agent`）。

- [ ] **Step 6: lint を通す**

Run: `git add roles/httpd tests && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて Passed（shellcheck と ansible-lint を含む）

- [ ] **Step 7: コミット**

```bash
git add roles/httpd/files/security-agent-pentest-counts roles/httpd/files/security-agent-pentest-counts.conf roles/httpd/tasks/security_agent.yml tests/test_security_agent_pentest.py
git commit -m "feat(httpd): send Security Agent pentest counts per 5-minute bucket"
```

### Task 3: CloudFront の枠の値を送る

**Files:**
- Modify: `roles/zabbix_aws/files/cloudfront_waf.sh`
- Modify: `tests/test_zabbix_aws.py`

**Interfaces:**
- Produces: trapper キー `cloudfront.bucket.requests` と `cloudfront.bucket.errors.5xx`（整数、時刻 B）。Task 5 がこのキーでアイテムを作る

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_zabbix_aws.py` にヘルパー `run_collector(bucket_rows, latest_rows="")` を足す。偽の `aws`、`date`、`zabbix_sender` を PATH の先頭に置いて `bash cloudfront_waf.sh` を動かす。
- 偽の `aws`: `describe-stacks` に `E123` を返す。`get-metric-data` では `--metric-data-queries` のファイルの Id を見て、Id が `bucket_` で始まれば `bucket_rows`、それ以外なら `latest_rows` を出す。前者で受け取った `--start-time` と `--end-time` を記録する
- 偽の `date`: `+%s` には `NOW`、`--iso-8601=seconds --date @N` には `iso(N)`、それ以外の `--iso-8601=seconds` には `iso(NOW)` を返す。`iso(n)` は `datetime.fromtimestamp(n, timezone.utc).isoformat()`
- 戻り値: `bucket_window`（記録した開始と終了の組）、`timestamped_args` と `timestamped_input`（`-T` つきの `zabbix_sender` 呼び出し。なければ `None`）、`latest_input`（`-T` なしの呼び出しの標準入力）

```python
NOW = 1794092400 + 700
BUCKET = (NOW // 300) * 300 - 600


class CloudfrontBucketTest(unittest.TestCase):
    def test_sends_bucket_requests_and_5xx_count(self):
        result = run_collector("bucket_requests\t1996.0\nbucket_rate_5xx\t13.977955911823647\n")
        self.assertIn("-T", result.timestamped_args)
        self.assertEqual(
            result.timestamped_input.splitlines(),
            [f"- cloudfront.bucket.requests {BUCKET} 1996", f"- cloudfront.bucket.errors.5xx {BUCKET} 279"],
        )

    def test_asks_for_exactly_the_bucket(self):
        result = run_collector("bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n")
        self.assertEqual(result.bucket_window, (iso(BUCKET), iso(BUCKET + 300)))

    def test_sends_nothing_without_bucket_data(self):
        result = run_collector("bucket_requests\tNone\nbucket_rate_5xx\tNone\n")
        self.assertIsNone(result.timestamped_input)

    def test_latest_values_are_still_sent(self):
        result = run_collector(
            "bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n",
            latest_rows="mcloudfront_requests\t733.0\n",
        )
        self.assertIn("- cloudfront.requests 733.0", result.latest_input)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_aws.py -v -k Bucket`
Expected: `test_sends_bucket_requests_and_5xx_count` と `test_asks_for_exactly_the_bucket` が FAIL（枠の呼び出しがまだない）。`test_sends_nothing_without_bucket_data` と `test_latest_values_are_still_sent` は PASS

- [ ] **Step 3: `fetch_bucket()` と `send_bucket()` を実装する**

`plan` と `fetch` はそのままにする。`bucket_start=$(( $(date +%s) / 300 * 300 - 600 ))` を求め、`Requests`（Sum、Id `bucket_requests`）と `5xxErrorRate`（Average、Id `bucket_rate_5xx`）の 2 クエリを別のクエリファイルに書く。`--start-time "$(date --iso-8601=seconds --date "@$bucket_start")"`、`--end-time` は `@$((bucket_start + 300))` として、2 回目の `get-metric-data` を `--query 'MetricDataResults[*].[Id,Values[0]]' --output text` で呼ぶ。両方の値が `None` でないときだけ、`printf '%.0f'` で丸めた `requests` と `requests * rate / 100` を `zabbix_sender -c /etc/zabbix/zabbix_agentd.conf -T -i -` に送る。一時ファイルは `my_exit` で消す。冒頭のコメントの「Everything is asked for in one request」を、最新値の 1 回と枠の 1 回の 2 回の呼び出しに合わせて書き直し、枠の定義と、fox と hotel のスクリプトが同じ枠を送ることを書く。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_aws.py -v`
Expected: 既存の 3 件を含めて 7 件 PASS

- [ ] **Step 5: lint を通す**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure`
Expected: すべて Passed

- [ ] **Step 6: コミット**

```bash
git add roles/zabbix_aws/files/cloudfront_waf.sh tests/test_zabbix_aws.py
git commit -m "feat(zabbix_aws): send CloudFront requests and 5xx per 5-minute bucket"
```

### Task 4: 適用

**Files:** なし（ホストへの適用）

- [ ] **Step 1: テスト全体を通す**

Run: `uv run --with pytest --with ansible-core pytest tests`
Expected: すべて PASS

- [ ] **Step 2: check で差分を見る**

Run:
```bash
direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-primary.yml --tags httpd_security_agent,teslamate_apache --check --diff
direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook home-secondary.yml --tags httpd_security_agent --check --diff
direnv exec /Volumes/ExternalHD/git/ansible-playbooks ansible-playbook cloud-workstation.yml --tags zabbix_aws_cloudfront_waf --check --diff
```
Expected: 終了コード 0。changed は、fox では Grafana の vhost、pentest の conf（diff は非表示）、スクリプト、agent の conf。hotel ではスクリプト、agent の conf、pentest の conf。alfa では `cloudfront_waf.sh` だけ

- [ ] **Step 3: 適用する**

Step 2 の 3 コマンドを `--check --diff` なしで実行する。
Expected: 終了コード 0、failed=0

- [ ] **Step 4: 2 回目で変更がないことを確かめる**

Step 3 をもう一度実行する。
Expected: すべて changed=0

- [ ] **Step 5: ログの新しい書式を確かめる**

Run: `ssh fox 'sudo apache2ctl -t' && curl -s -o /dev/null https://grafana.rewse.jp/ -H "X-Security-Agent-Pentest: $(direnv exec /Volumes/ExternalHD/git/ansible-playbooks op read op://ansible/m6obpvalg7ekdi5nsf4yx6wi3q/password)" && ssh fox tail -1 /var/log/apache2/security_agent_pentest.log`
Expected: `Syntax OK` のあと、`<epoch> <address> 302 -` の形の 4 列の行。家からは UniFi の DNS で fox に直接届くため 4 列目は `-` になる

- [ ] **Step 6: UserParameter を呼ぶ**

AGENTS.md のとおり、fox から各 agent に聞く。
Run: `ssh fox 'zabbix_get -s zabbix.rewse.jp -k security_agent.sender; zabbix_get -s hotel.rewse.jp -k security_agent.sender; zabbix_get -s alfa.rewse.jp -k cloudfront_waf.sender'`
Expected: それぞれ数字 1 行。Zabbix のアイテムがまだないため、`security_agent.sender` は `2`（値が拒否された）でよい。アイテムがない今だけ手で呼んでよい。Task 5 のあとに手で呼ぶと同じ枠が 2 回入り、差し引きがずれる

### Task 5: Zabbix のアイテムとトリガー

**Files:** なし（Zabbix API を `mcporter call zabbix.*` で操作）

**Interfaces:**
- Consumes: Task 2 と Task 3 の trapper キー
- Produces: テンプレート 10227 の計算アイテム `cloudfront.public.requests`、`cloudfront.public.errors.5xx`、`cloudfront.public.error_rate.5xx`

- [ ] **Step 1: fox と hotel のアイテムを作る**

テンプレート `MyTemplate App Apache CloudFront`（hostid 10228）に `item_create` で 3 つ作る。
- `Security Agent pentest counter`: key `security_agent.sender`、type 0（Zabbix agent）、value_type 3、delay `5m`、history `1w`、trends `0`
- `Security Agent pentest requests`: key `security_agent.requests`、type 2（trapper）、value_type 3、history `1w`、trends `450d`
- `Security Agent pentest 5xx responses`: key `security_agent.errors.5xx`、ほかは 1 つ前と同じ

Expected: それぞれ itemid が返る

- [ ] **Step 2: alfa の trapper アイテムを作る**

テンプレート `MyTemplate AWS CloudFront WAF`（hostid 10227）に、`CloudFront requests per bucket`（`cloudfront.bucket.requests`）と `CloudFront 5xx responses per bucket`（`cloudfront.bucket.errors.5xx`）を type 2、value_type 3、history `1w`、trends `450d` で作る。
Expected: それぞれ itemid が返る

- [ ] **Step 3: 計算アイテムを作る**

テンプレート 10227 に type 15、value_type 0、delay `5m`、history `1w`、trends `450d` で 3 つ作る。R と E は次の式で、params には文字どおり展開して書く。

```
R = sum(//cloudfront.bucket.requests,15m:now-15m)-sum(sum_foreach(/*/security_agent.requests,15m:now-15m))
E = sum(//cloudfront.bucket.errors.5xx,15m:now-15m)-sum(sum_foreach(/*/security_agent.errors.5xx,15m:now-15m))
```

- `CloudFront requests excluding Security Agent`: key `cloudfront.public.requests`、params `max(R,0)`
- `CloudFront 5xx responses excluding Security Agent`: key `cloudfront.public.errors.5xx`、params `max(E,0)`
- `CloudFront 5xx error rate excluding Security Agent`: key `cloudfront.public.error_rate.5xx`、units `%`、params `100*max(E,0)/max(R,1)`

API が `sum_foreach` の時間シフトを拒んだときは、`sum(sum_foreach(/*/K,15m:now-15m))` を `(sum(/fox.rewse.jp/K,15m:now-15m)+sum(/hotel.rewse.jp/K,15m:now-15m))` に置き換える。この形では片方のホストに値がないと計算アイテムが unsupported になり、spec の制約を満たさない。置き換えた場合はトリガーの代わりの判定で検知が続くことをユーザーに報告する。
Expected: それぞれ itemid が返る

- [ ] **Step 4: トリガーを置き換える**

テンプレートのトリガー 17035 を `trigger_update` で更新する。`T` を `/MyTemplate AWS CloudFront WAF` として、expression を次の式にし、opdata を `{ITEM.LASTVALUE1}, {ITEM.LASTVALUE2}`（除外後の率とリクエスト数）にする。名前と重大度は変えない。

```
(last(T/cloudfront.public.error_rate.5xx)>5 and last(T/cloudfront.public.requests)>=50) or (min(T/cloudfront.error_rate.5xx,15m)>5 and count(T/cloudfront.error_rate.5xx,15m)>=3 and sum(T/cloudfront.requests,15m)>=30 and nodata(T/cloudfront.public.error_rate.5xx,30m)=1)
```

Expected: triggerids に 17035 が返る。`trigger_get` で見た alfa のトリガー 17039 の expression が、`/alfa.rewse.jp/` の同じ式になっている

- [ ] **Step 5: zabbix-server を再起動する**

Run: `ssh fox 'sudo systemctl restart zabbix-server && systemctl is-active zabbix-server'`
Expected: `active`

- [ ] **Step 6: 値が入ることを確かめる**

40 分待ってから、`item_get` で fox、hotel、alfa の新しいアイテムの `lastvalue`、`lastclock`、`state`、`error` を見る。
Expected: trapper アイテムの `lastclock` が 300 の倍数。計算アイテム 3 つが `state` 0（supported）で値を持ち、`error` が空。alfa のトリガー 17039 の `value` が 0

### Task 6: 当日の値で確かめて仕上げる

**Files:**
- Move: `docs/superpowers/specs/2026-11-08-cloudfront-5xx-exclude-security-agent-design.md` → `docs/superpowers/archive/specs/`
- Move: `docs/superpowers/plans/2026-11-08-cloudfront-5xx-exclude-security-agent.md` → `docs/superpowers/archive/plans/`

- [ ] **Step 1: 2026-11-08 の枠で除外後の値を確かめる**

アクセスログで数えた 07:10、07:15、07:20 の枠のペンテストの (リクエスト数, 5xx 数) は (1238, 110)、(1988, 279)、(1781, 156)。CloudWatch では (1252, 111)、(1996, 279)、(1788, 157) だった。除外後のリクエスト数は 29、5xx 数は 2 で、リクエスト数が 50 未満のため新しい式は発火しない。この計算を最終報告に書き、Task 5 Step 6 の計算アイテムの値と式が同じ形で出ていることを確かめる。
Expected: 新しい式の条件が偽

- [ ] **Step 2: マージして push する**

Global Constraints のワークツリーから main へ `--no-ff` でマージし、同じマージコミットで spec と plan を archive に移す。push の前に `uvx pre-commit run --all-files` と `uv run --with pytest --with ansible-core pytest tests` を通す。
Expected: `git push origin HEAD:refs/heads/main` が成功し、GitHub Actions の pre-commit が通る
