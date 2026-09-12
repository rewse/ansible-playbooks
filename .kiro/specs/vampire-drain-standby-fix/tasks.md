# Vampire Drain Standby集計修正 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: `subagent-driven-development`を使い、タスクごとに実装とレビューを分離する。

**Goal:** Vampire DrainのStandby集計を状態区間と駐車区間の実重複秒で計算し、上流PRと公式修正版リリースまでの一時Ansibleパッチを安全に提供する。

**Architecture:** TeslaMate Forkでは`vampire-drain.json`のSQLだけを修正する。Ansibleは公式Grafanaイメージから同JSONを抽出し、専用パッチャーで同じ変更を適用して読み取り専用でマウントする。SQL、性能、本番表示、PR内容を順番に検証し、前段が失敗した場合は次へ進まない。

**Tech Stack:** PostgreSQL、Grafana dashboard JSON、Python 3標準ライブラリ、Ansible、Docker Compose、agent-browser、GitHub CLI

## 全体制約

- 対象はVampire DrainのStandby集計だけとする。
- 上流PRは`grafana/dashboards/vampire-drain.json`だけを変更する。
- 本番表示検証が完了するまでForkをcommitまたはpushしない。
- PRタイトルと本文はユーザーが明示承認するまでsubmitしない。
- 本番DBへの検証は読み取り専用クエリだけを使う。
- 一時パッチは公式`teslamate/grafana`イメージを維持し、Forkイメージを運用しない。
- 既存のGeoFence関連未コミット差分をVampire Drainのcommitへ混ぜない。
- PRがマージされても直ちにパッチを削除しない。修正を含む公式イメージを本番へ導入して表示確認後に削除する。
- 公開PRには環境固有のホスト名、位置、VIN、時刻、認証情報を記載しない。

---

### Task 1: SQLの正しさと性能を読み取り専用で検証する

**Files:**
- Create: `/Volumes/ExternalHD/git/ansible-playbooks/.kiro/specs/vampire-drain-standby-fix/validation.md`
- Inspect: `/Users/tats/Playground/teslamate/grafana/dashboards/vampire-drain.json`

**Interfaces:**
- Consumes: GrafanaのTeslaMate PostgreSQL datasource、設計書の半開区間仕様
- Produces: 実データ比較、合成境界ケース、`EXPLAIN (ANALYZE, BUFFERS)`の結果を記録した`validation.md`

- [ ] **Step 1: 現行SQLと修正SQLを抽出する**

ForkのJSONから`rawSql`を取得し、Grafana変数を本番の車両ID、90日、6時間、`rated`へ展開する。現行SQLは`upstream/main`から取得する。

Run:

```bash
git -C /Users/tats/Playground/teslamate show upstream/main:grafana/dashboards/vampire-drain.json > /tmp/vampire-drain-current.json
python3 -m json.tool /Users/tats/Playground/teslamate/grafana/dashboards/vampire-drain.json >/dev/null
```

Expected: JSON検査が終了コード0で完了する。

- [ ] **Step 2: 合成境界ケースを読み取り専用CTEで検証する**

`VALUES`だけで駐車区間と状態区間を作り、次を1クエリで検証する。

```sql
WITH parking(name, start_date, end_date) AS (
  VALUES
    ('contained', timestamp '2026-01-01 10:00', timestamp '2026-01-01 20:00'),
    ('cross_start', timestamp '2026-01-01 10:00', timestamp '2026-01-01 20:00'),
    ('cross_end', timestamp '2026-01-01 10:00', timestamp '2026-01-01 20:00'),
    ('cross_both', timestamp '2026-01-01 10:00', timestamp '2026-01-01 20:00'),
    ('open_end', timestamp '2026-01-01 10:00', timestamp '2026-01-01 20:00'),
    ('thirty_one_days', timestamp '2026-07-01 00:00', timestamp '2026-08-01 00:00')
),
states(name, start_date, end_date) AS (
  VALUES
    ('contained', timestamp '2026-01-01 11:00', timestamp '2026-01-01 19:00'),
    ('cross_start', timestamp '2026-01-01 09:00', timestamp '2026-01-01 19:00'),
    ('cross_end', timestamp '2026-01-01 11:00', timestamp '2026-01-01 21:00'),
    ('cross_both', timestamp '2026-01-01 09:00', timestamp '2026-01-01 21:00'),
    ('open_end', timestamp '2026-01-01 11:00', NULL),
    ('thirty_one_days', timestamp '2026-07-01 00:00', timestamp '2026-08-01 00:00')
)
SELECT
  p.name,
  EXTRACT(EPOCH FROM (p.end_date - p.start_date)) AS duration,
  EXTRACT(EPOCH FROM (
    LEAST(COALESCE(s.end_date, p.end_date), p.end_date)
    - GREATEST(s.start_date, p.start_date)
  )) AS overlap,
  EXTRACT(EPOCH FROM (
    LEAST(COALESCE(s.end_date, p.end_date), p.end_date)
    - GREATEST(s.start_date, p.start_date)
  )) / EXTRACT(EPOCH FROM (p.end_date - p.start_date)) AS standby
FROM parking p
JOIN states s USING (name)
WHERE s.start_date < p.end_date
  AND COALESCE(s.end_date, p.end_date) > p.start_date
ORDER BY p.name;
```

Expected:

```text
contained=0.8
cross_start=0.9
cross_end=0.9
cross_both=1.0
open_end=0.9
thirty_one_days=1.0
```

- [ ] **Step 3: 本番実データで現行結果と修正結果を比較する**

Grafana datasource APIを管理セッションで呼び出す。資格情報はコンテナ環境からホスト内で取得し、標準出力へ出さない。

Expected:

```text
69,445秒区間: offline=68,314秒、online=1,131秒、修正Standby約0.984
28,422秒区間: offline=104秒、online=28,318秒、修正Standby約0.004
```

完全内包された既存の97%から100%区間は、丸め表示が変わらないことも確認する。全行について`0 <= standby <= 1`をassertする。

- [ ] **Step 4: 現行SQLと修正SQLへEXPLAINを実行する**

Run: Grafana datasource API経由で両クエリへ`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`を実行する。

Expected: 3回実行の中央値で、修正SQLの実行時間とshared block read/hit合計が現行SQLの2倍以内に収まり、`states`への新しい無条件Seq Scanがない。閾値を超えた場合はPRへ進まず、実行計画とインデックス利用を再検討する。結果を`validation.md`へ記録する。

- [ ] **Step 5: 検証記録をレビューする**

`validation.md`にはSQL、匿名化した結果、実行計画の要約、判定を記載する。ホスト名、位置、VIN、実時刻は記載しない。

---

### Task 2: Vampire Drain専用AnsibleパッチャーをTDDで実装する

**Files:**
- Create: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/files/patch_vampire_drain_dashboard.py`
- Create: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/test_patch_vampire_drain_dashboard.py`

**Interfaces:**
- Consumes: `patch_dashboard(dashboard: dict) -> dict`へ渡す公式dashboard JSON
- Produces: `v.duration`と2つのLATERAL集計を修正したJSON、CLIの`changed`または`unchanged`

- [ ] **Step 1: 失敗する単体テストを書く**

`test_patch_vampire_drain_dashboard.py`には最小のdashboard fixtureと具体的なassertを置く。

```python
SOURCE_QUERY = """WITH v AS (
  SELECT EXTRACT(EPOCH FROM age(t.start_date, lag(t.end_date) OVER w)) AS duration
  FROM merge t WINDOW w AS (ORDER BY t.start_date)
)
SELECT * FROM v,
LATERAL (
  SELECT EXTRACT(EPOCH FROM sum(age(s.end_date, s.start_date))) AS sleep
  FROM states s
  WHERE state = 'asleep'
    AND v.start_date <= s.start_date AND s.end_date <= v.end_date
) s_asleep,
LATERAL (
  SELECT EXTRACT(EPOCH FROM sum(age(s.end_date, s.start_date))) AS sleep
  FROM states s
  WHERE state = 'offline'
    AND v.start_date <= s.start_date AND s.end_date <= v.end_date
) s_offline
"""


def make_dashboard(query=SOURCE_QUERY):
    return {"panels": [{"targets": [{"rawSql": query}]}]}


def test_patch_clips_asleep_and_offline_to_parking_interval():
    patched = patch_dashboard(make_dashboard())
    query = patched["panels"][0]["targets"][0]["rawSql"]
    assert query.count("LEAST(COALESCE(s.end_date, v.end_date), v.end_date)") == 2
    assert query.count("s.start_date < v.end_date") == 2


def test_patch_replaces_age_duration_with_elapsed_seconds():
    patched = patch_dashboard(make_dashboard())
    query = patched["panels"][0]["targets"][0]["rawSql"]
    assert "t.start_date - lag(t.end_date) OVER w" in query
    assert "age(t.start_date" not in query
```

同じfixtureを変形し、状態集計が1件または3件の場合、duration式が0件または2件の場合に`ValueError`になることをassertする。2回適用時のJSON一致と、同一内容を書き込んだ場合のmtime維持もassertする。

- [ ] **Step 2: REDを確認する**

Run:

```bash
python3 -m unittest roles/teslamate/tests/test_patch_vampire_drain_dashboard.py
```

Expected: 実装ファイルがない、または関数がないため失敗する。

- [ ] **Step 3: 最小実装を書く**

パッチャーはJSONを再帰走査し、Vampire Drainパネルの`rawSql`を1件だけ特定する。次を期待数付きで置換する。

```text
EXTRACT(EPOCH FROM age(t.start_date, lag(t.end_date) OVER w))
→ EXTRACT(EPOCH FROM (t.start_date - lag(t.end_date) OVER w))
```

```text
sum(age(s.end_date, s.start_date))
→ sum(LEAST(COALESCE(s.end_date, v.end_date), v.end_date)
      - GREATEST(s.start_date, v.start_date))
```

```text
v.start_date <= s.start_date AND s.end_date <= v.end_date
→ s.start_date < v.end_date
  AND COALESCE(s.end_date, v.end_date) > v.start_date
```

CLIは`--input`と`--output`を受け取り、内容が変わった場合だけ原子的に書き換える。

- [ ] **Step 4: GREENを確認する**

Run:

```bash
python3 -m unittest roles/teslamate/tests/test_patch_vampire_drain_dashboard.py
```

Expected: 全テスト成功。

- [ ] **Step 5: TeslaMate v4.2.0とmainの実JSONでスモークテストする**

Run:

```bash
for ref in v4.2.0 main; do
  curl -fsSL "https://raw.githubusercontent.com/teslamate-org/teslamate/${ref}/grafana/dashboards/vampire-drain.json" > "/tmp/vampire-${ref}.json"
  python3 roles/teslamate/files/patch_vampire_drain_dashboard.py \
    --input "/tmp/vampire-${ref}.json" \
    --output "/tmp/vampire-${ref}-patched.json"
done
```

Expected: 初回`changed`、同じ入力で2回目`unchanged`、修正箇所の期待数が一致する。

---

### Task 3: Ansibleの抽出・マウント処理へ統合する

**Files:**
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tasks/main.yml`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/templates/compose.yml.j2`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/render_templates.yml`
- Inspect: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/fixtures.yml`

**Interfaces:**
- Consumes: Task 2のCLI、解決済み`teslamate_grafana_image_ref`
- Produces: `/srv/teslamate/grafana-dashboards/vampire-drain.json`とread-only bind mount

- [ ] **Step 1: 既存の未コミット差分を記録する**

Run:

```bash
git -C /Volumes/ExternalHD/git/ansible-playbooks status --short
git -C /Volumes/ExternalHD/git/ansible-playbooks diff -- roles/teslamate > /tmp/teslamate-role-before-vampire.patch
```

既存のGeoFence差分を維持し、Vampire Drain用には専用ファイルと分離可能なhunkを追加する。

- [ ] **Step 2: 公式JSONの抽出対象へVampire Drainを追加する**

停止コンテナから次をコピーする。

```text
/dashboards/vampire-drain.json
→ /srv/teslamate/grafana-dashboards/vampire-drain.upstream.json
```

イメージ内コードは実行せず、既存の`docker create`と`docker cp`を使う。

- [ ] **Step 3: 専用パッチャーを実行するタスクを追加する**

`python3 patch_vampire_drain_dashboard.py`を実行し、標準出力が`changed`のときだけGrafana再作成を通知する。check modeでは抽出とパッチを行わない。公式イメージ参照のいずれかが空の場合は実行しない。

- [ ] **Step 4: Composeへread-only mountを追加する**

```yaml
- {{ teslamate_data_dir }}/grafana-dashboards/vampire-drain.json:/dashboards/vampire-drain.json:ro
```

- [ ] **Step 5: テンプレート契約テストを追加する**

`render_templates.yml`で上記mountが存在することをassertする。

- [ ] **Step 6: Ansibleローカル検証を実行する**

Run:

```bash
python3 -m unittest \
  roles/teslamate/tests/test_patch_visited_dashboard.py \
  roles/teslamate/tests/test_patch_vampire_drain_dashboard.py
ansible-playbook roles/teslamate/tests/render_templates.yml -i localhost, --syntax-check
ansible-playbook roles/teslamate/tests/render_templates.yml -i localhost,
ansible-lint roles/teslamate/tasks/main.yml roles/teslamate/tests/render_templates.yml
git diff --check
```

Expected: 全コマンド成功。

- [ ] **Step 7: コードレビューを実施する**

`code-reviewer`へPython、Ansible、SQL、冪等性、check mode、既存GeoFence差分との分離をレビューさせる。HIGH以上の指摘を解消して再検証する。

---

### Task 4: 本番へ一時適用して表示を検証する

**Files:**
- Update: `/Volumes/ExternalHD/git/ansible-playbooks/.kiro/specs/vampire-drain-standby-fix/validation.md`

**Interfaces:**
- Consumes: Task 3の一時パッチ、`singleton_int1.yml`、fox.rewse.jp
- Produces: 本番適用結果、Grafana API検証、browser-automation証跡、ロールバック判定

- [ ] **Step 1: check modeを実行する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate \
  --check --diff
```

Expected: `failed=0`、Vampire Drain専用patcherの配備とcomposeのread-only mountだけが新規差分として現れる。非変更のcheck modeではイメージからの抽出とJSON生成をskipし、生成JSONは本適用後のStep 3でassertする。予期しない変更があれば停止する。

- [ ] **Step 2: 本番へ適用する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate
```

Expected: `failed=0`、Grafanaが再作成される。

- [ ] **Step 3: ファイルとmountを検証する**

対象ホストで次をassertする。

```text
生成JSONに実経過秒と2つの重複クリップ条件がある
/dashboards/vampire-drain.jsonのmountが1件
mountはread-only
Grafana /api/healthのdatabaseがok
```

- [ ] **Step 4: Grafana APIの読み込み済みクエリを確認する**

`/api/dashboards/uid/zhHx2Fggk`から`rawSql`を取得し、生成ファイルと同じ3変更を含むことをassertする。

- [ ] **Step 5: browser-automationで90日表示を確認する**

認証済みの専用agent-browserセッションでVampire Drainを開き、次を確認する。

```text
誤表示区間: Standby 98%付近
真のオンライン区間: Standby 0%付近、SoC -3%
既存正常区間: 97%から100%表示を維持
パネル、リンク、期間、車両変数: 正常
```

スクリーンショットはローカル検証用とし、個人情報を含む未加工画像をPRへ添付しない。

- [ ] **Step 6: Grafanaログを確認する**

直近10分のログにdashboard provisioning、PostgreSQL query、JSON読み込みのエラーがないことを確認する。

- [ ] **Step 7: Playbookを再実行して冪等性を確認する**

Expected: `changed=0`。一時コンテナの作成・削除タスクは運用上`ok`として扱い、Grafana再作成が発生しないことを確認する。

- [ ] **Step 8: 失敗時だけロールバックする**

Vampire Drainのmountを除去し、Grafanaを再作成する。DBやTeslaMate本体は変更しない。失敗内容を`validation.md`へ記録し、Forkのcommit/pushへ進まない。

---

### Task 5: 上流差分を最終検証してcommit・pushする

**Files:**
- Modify: `/Users/tats/Playground/teslamate/grafana/dashboards/vampire-drain.json`

**Interfaces:**
- Consumes: Task 4で検証済みのSQL
- Produces: `fix/vampire-drain-overlapping-states`ブランチの単一commitとorigin上のbranch

- [ ] **Step 1: 本番検証済みSQLとFork差分を照合する**

Grafana APIから取得したSQLとForkの`rawSql`について、`v.duration`と2つのLATERAL集計が一致することをassertする。

- [ ] **Step 2: TeslaMate開発ガイドの静的検証を実行する**

Run:

```bash
python3 -m json.tool grafana/dashboards/vampire-drain.json >/dev/null
git diff --check
```

利用可能な方法を順に試す。

```bash
treefmt --fail-on-change
# treefmtがなければ
nix run .#lint
```

Nix開発環境と`teslamate_test`を既存手順で準備できる場合は次も実行する。

```bash
mix ci
```

実行できない場合は理由と代替検証を`validation.md`およびPR本文へ記載する。

- [ ] **Step 3: 最終コードレビューを実施する**

`code-reviewer`へPostgreSQL時間計算、NULL、半開区間、100%超過、JSON差分、公開情報をレビューさせる。承認されるまでcommitしない。

- [ ] **Step 4: 上流差分だけをcommitする**

Run:

```bash
git add grafana/dashboards/vampire-drain.json
git diff --cached --check
git commit -m 'fix(grafana): clip standby states to parking periods'
```

- [ ] **Step 5: 作業ブランチをpushする**

Run:

```bash
git push -u origin fix/vampire-drain-overlapping-states
```

`main`へ直接pushしない。

---

### Task 6: PR文面を作成してユーザーレビューを受ける

**Files:**
- Create: `/Users/tats/Playground/teslamate/.git/pr-vampire-drain.md`

**Interfaces:**
- Consumes: Task 1から5の匿名化済み検証結果
- Produces: 70文字未満のPRタイトルと英語PR本文。PR自体は作成しない。

- [ ] **Step 1: PRタイトルを作る**

候補:

```text
Fix standby time for states crossing parking boundaries
```

- [ ] **Step 2: PR本文を作る**

本文には次を含める。

```markdown
## Summary
- clip asleep and offline states to the parking interval
- calculate both standby time and parking duration from elapsed seconds

## Problem
Parking periods and vehicle states come from different event streams, so their timestamps do not always align. A state can normally begin before a parking period or end after it.

Parking: 10:00 |----------------| 20:00
Offline:       10:05 |---------------| 20:02
Overlap:       10:05 |------------| 20:00

The previous full-containment predicates discard the entire overlapping state. In an anonymized production example, 68,314 of 69,445 seconds were offline, but the dashboard displayed 0% standby.

## Implementation
Explain half-open overlap predicates, clipped intervals, NULL end dates, and replacement of age() with timestamp subtraction.

## Validation
Include synthetic boundary cases, anonymized real-data results, EXPLAIN ANALYZE summary, browser verification, formatting, and mix ci status.

---

🤖 Assisted by GPT-5.6-sol (OpenAI) via Kiro CLI (planning, implementation, testing, and PR description).
```

- [ ] **Step 3: 公開情報を監査する**

ホスト名、位置、VIN、実時刻、認証情報がないことを確認する。スクリーンショットは添付しない。

- [ ] **Step 4: PR文面をユーザーへ提示する**

ここで実行を停止する。明示承認を得るまで`gh pr create`を実行しない。

---

### Task 7: 承認後にPRを作成し、一時パッチを正式化する

**Files:**
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/files/patch_vampire_drain_dashboard.py`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/.kiro/specs/vampire-drain-standby-fix/validation.md`
- Partially stage: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tasks/main.yml`
- Partially stage: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/templates/compose.yml.j2`
- Partially stage: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/render_templates.yml`

**Interfaces:**
- Consumes: ユーザー承認済みPR文面、Task 5のpush済みbranch
- Produces: 上流PR URL、URL付き一時パッチのAnsible commit、本番適用済み状態

- [ ] **Step 1: 承認済み文面でPRを作成する**

Run:

```bash
gh pr create \
  --repo teslamate-org/teslamate \
  --base main \
  --head rewse:fix/vampire-drain-overlapping-states \
  --title 'Fix standby time for states crossing parking boundaries' \
  --body-file .git/pr-vampire-drain.md
```

Expected: PR URLを取得する。CLA Assistantが要求した場合はFLA 2.0の手続きをユーザーへ案内する。

- [ ] **Step 2: AnsibleパッチャーへPR URLと廃止条件を追加する**

PR作成コマンドが返したURLを`upstream_pr_url`として保持し、パッチャーへ次の形式で埋め込む。

```python
comment = f"""# Temporary workaround for {upstream_pr_url}.
# Remove this patch after deploying an official TeslaMate Grafana image
# that contains the upstream fix.
"""
```

`upstream_pr_url`が`https://github.com/teslamate-org/teslamate/pull/`で始まることをassertしてから書き込む。

- [ ] **Step 3: Ansibleを再検証・再適用する**

Task 3の全ローカル検証、check mode、本適用、Grafana API確認、browser-automation、冪等性確認を繰り返す。

- [ ] **Step 4: Vampire Drain関連hunkだけをstageする**

既存GeoFence差分を混ぜない。

```bash
git add roles/teslamate/files/patch_vampire_drain_dashboard.py
git add roles/teslamate/tests/test_patch_vampire_drain_dashboard.py
git add .kiro/specs/vampire-drain-standby-fix/validation.md
git add -p roles/teslamate/tasks/main.yml
git add -p roles/teslamate/templates/compose.yml.j2
git add -p roles/teslamate/tests/render_templates.yml
git diff --cached --check
git diff --cached --stat
```

- [ ] **Step 5: 一時パッチをcommitする**

```bash
git commit -m 'fix(teslamate): patch Vampire Drain standby calculation'
```

- [ ] **Step 6: 最終状態を記録する**

`validation.md`へPR URL、適用した公式イメージdigest、Grafana API確認、browser-automation結果、冪等性結果、将来の削除条件を記録する。

---

## 実行停止条件

次の場合は直ちに停止し、後続タスクへ進まない。

- 修正SQLのStandbyが0%未満または100%を超える。
- 真のオンライン区間が高いStandbyへ変わる。
- `EXPLAIN ANALYZE`で重大な性能退行がある。
- パッチ対象の件数が期待値と一致しない。
- Grafana APIが修正済みSQLを返さない。
- browser-automationでパネルまたはリンクに回帰がある。
- 2回目のPlaybookがGrafanaを再作成する。
- PR文面に環境固有情報が含まれる。
