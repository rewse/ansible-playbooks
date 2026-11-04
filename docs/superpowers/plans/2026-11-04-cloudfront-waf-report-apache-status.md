# CloudFront WAF 週次レポート Apache 応答コード 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抽出 4（`allowed_scans`）の候補に fox の Apache の応答コードを付け、3xx と 4xx だけのものを kiro-cli に渡す前に捨てる。

**Architecture:** スクリプトに Apache のログを読む関数を足し、`main` で `allowed_scans` の行に適用する。kiro-cli にはツールを渡さない。

**Tech Stack:** Python 3.12 標準ライブラリ（`gzip`、`re`、`collections.Counter`）。

**Spec:** `docs/superpowers/specs/2026-11-04-cloudfront-waf-report-design.md` の「Apache の応答コードによる絞り込み」

## Global Constraints

- 対象は `allowed_scans` だけ。`www.rewse.jp` は `rewse.jp` と同じ。`access.log` の行は `rewse.jp` 宛て。パスはクエリ文字列を除いて比べる。
- 3xx と 4xx だけなら捨てる。2xx か 5xx を含むもの、`不明` は残す。ログが読めなければすべて `不明`。

## Review Focus

- ログに壊れた行やバイナリが混ざる: その行を飛ばす。テストは `test_origin_statuses_skips_malformed_lines`。
- ローテーション済みの `.gz` だけに前週の行がある: 読める。テストは `test_origin_statuses_reads_rotated_gzip`。

---

### Task 1: 応答コードの付与と絞り込み

**Files:**
- Modify: `roles/cloudfront_waf_report/files/cloudfront-waf-report`、`roles/cloudfront_waf_report/templates/config.json.j2`
- Test: `tests/test_cloudfront_waf_report.py`、`tests/test_cloudfront_waf_report_role.py`

**Interfaces:**
- Produces:
  - `origin_statuses(log_dir: pathlib.Path, period: tuple[datetime, datetime]) -> dict[tuple[str, str, str], collections.Counter[str]]`: キーは `(host, path, client_ip)`。
  - `annotate_scans(rows: list[dict[str, str]], statuses: dict) -> list[dict[str, str]]`: 各行に `origin_status` を付け、3xx と 4xx だけの行を除く。`origin_status` は `"200×1, 404×2"` のようにコード順、無ければ `"不明"`。
  - config のキー `apache_log_dir`（既定 `/var/log/apache2`）。

- [ ] **Step 1: テストを書く** — `test_origin_statuses_parses_both_formats`、`test_origin_statuses_reads_rotated_gzip`、`test_origin_statuses_skips_malformed_lines`、`test_origin_statuses_ignores_lines_outside_period`、`test_origin_statuses_returns_empty_when_unreadable`、`test_annotate_scans_drops_only_redirects_and_client_errors`、`test_annotate_scans_marks_unknown`、`test_annotate_scans_treats_www_as_apex`、`test_main_filters_allowed_scans_by_apache_status`、`test_prompt_explains_origin_status`、role の `test_config_template_renders_valid_json` に `apache_log_dir` を足す。
- [ ] **Step 2: 失敗を確かめる** — `uv run --with pytest --with ansible-core pytest tests/test_cloudfront_waf_report.py tests/test_cloudfront_waf_report_role.py -q` が FAIL
- [ ] **Step 3: 実装する** — `main` では `prepare_rows` のあとで `allowed_scans` にだけ `annotate_scans` を適用する。`office` の行は IP を消してあるので照合できず `不明` になるが、`allowed_scans` はオフィスを除いているので起きない。
- [ ] **Step 4: 通ることを確かめる** — PASS、`uv run --with pytest --with ansible-core pytest tests -q` と pre-commit が通る
- [ ] **Step 5: fox で dry run** — 前回と同じ方法で dry run し、`/.env*` のような 404 の項目が消えること
- [ ] **Step 6: コミット** — `feat(cloudfront_waf_report): drop allowed scans that Apache answered with an error`
