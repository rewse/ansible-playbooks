# Vampire Drain Standby集計修正の設計

## 目的

TeslaMateのVampire Drainダッシュボードは、駐車区間に完全に収まる`asleep`と`offline`の状態だけをStandby時間へ加算している。状態が駐車区間の境界をまたぐと集計から外れるため、実際には大半が`offline`でもStandby 0%と表示される場合がある。本設計では、状態区間と駐車区間の重複時間を集計するよう上流ダッシュボードを修正し、修正版を含む公式Grafanaイメージが利用可能になるまでAnsibleで一時パッチを適用する。

対象はVampire DrainのStandby集計だけとする。GeoFence内の軌跡除外は別の運用要件であり、本設計には含めない。

## 確認済みの現象

本番データで次の2区間を確認した。

- 69,445秒の駐車区間では、`offline`が68,314秒、`online`が1,131秒重なっていた。実際のStandbyは約98.4%だが、現行ダッシュボードは0%と表示した。
- 28,422秒の駐車区間では、`online`が28,318秒、`offline`が104秒だった。この区間のStandbyは約0.4%で、0%表示は実態に近い。

現行SQLは次の完全内包条件を使っている。

```sql
v.start_date <= s.start_date
AND s.end_date <= v.end_date
```

この条件では、開始または終了境界をまたぐ正常な状態レコードを丸ごと除外する。

## 採用する進め方

本番相当の表示検証を終えてから上流PRを作成する。

1. 本番データに対して修正SQLを読み取り専用で実行する。
2. 合成データで境界ケースを検証する。
3. `EXPLAIN (ANALYZE, BUFFERS)`で性能を確認する。
4. Ansibleへ一時パッチを未コミットで実装する。
5. check modeを実行してから本番へ適用する。
6. browser-automationとGrafana APIで表示と読み込み済みクエリを確認する。
7. Playbookを再実行して冪等性を確認する。
8. 検証に合格したForkの差分をcommitし、作業ブランチをpushする。
9. PRタイトルと本文を提示し、明示承認を得る。
10. 承認後にPRを作成する。
11. PR URLと廃止条件をAnsibleのコメントへ記録して正式化する。

外部ForkのPRにはTeslaMate公式のPR用Dockerイメージが自動生成されないため、PR後のイメージ検証には依存しない。一時パッチを先に長期運用してから上流化する方法も採らない。一時パッチが恒久化しやすいためである。

## 責務分離

### TeslaMate Fork

`grafana/dashboards/vampire-drain.json`だけを変更する。駐車区間と状態区間の重複時間を計算し、Standbyの分子と分母を実経過秒へ統一する。Ansible固有の処理やローカル環境の情報は含めない。

### Ansible

公式`teslamate/grafana`イメージから`/dashboards/vampire-drain.json`を抽出し、上流修正と同じSQL変換を適用する。生成したファイルをホストへ保存し、Grafanaコンテナへ読み取り専用でbind mountする。

### 検証ゲート

SQLの正しさ、性能、本番表示、PR内容を独立したゲートとして扱う。前のゲートが失敗した場合は次へ進まない。

## SQL計算仕様

駐車区間を`[v.start_date, v.end_date)`、状態区間を`[s.start_date, s.end_date)`の半開区間として扱う。端点だけが接する状態は重複時間0なので集計しない。

重複判定は次のとおりとする。

```sql
s.start_date < v.end_date
AND COALESCE(s.end_date, v.end_date) > v.start_date
```

重複時間は状態区間を駐車区間へクリップして求める。

```sql
LEAST(COALESCE(s.end_date, v.end_date), v.end_date)
- GREATEST(s.start_date, v.start_date)
```

`states.end_date IS NULL`の場合は、対象となる駐車区間の終了まで状態が続いたものとして扱う。クリップ済みの`asleep`と`offline`を合計し、Standbyの分子とする。

分母は`age()`を使わず、timestamp差から実経過秒を求める。

```sql
EXTRACT(
  EPOCH FROM (
    t.start_date - lag(t.end_date) OVER w
  )
)
```

`age()`は暦月を含むintervalを返し、epoch変換では1か月を30日として扱う。分子だけをtimestamp差へ変えると、31日区間などでStandbyが100%を超えうるため、分母も同じ時間表現へ統一する。

正常データのStandbyは`0 <= standby <= 1`を満たす。破損データで状態レコードが重複し、合計が100%を超えた場合は、`LEAST(..., 1)`で隠さず検証エラーとして扱う。

## 一時Ansibleパッチ

既存のダッシュボード抽出処理へ`vampire-drain.json`を追加する。GeoFence軌跡除外とは目的が異なるため、Vampire Drain用の変換処理を分離する。

パッチャーの契約は次のとおりとする。

- 入力は公式イメージから抽出した`vampire-drain.json`とする。
- `v.duration`、`asleep`のLATERAL集計、`offline`のLATERAL集計をそれぞれ期待数だけ修正する。
- 対象がない、対象が重複している、上流SQLの形が変わっている場合は失敗する。
- 失敗時は既存コンテナと既存の修正済みJSONを維持し、未修正ダッシュボードへ自動的に戻さない。
- 同じ公式イメージからは同じJSONを生成し、再実行時は変更なしとする。

生成ファイルを次のパスへマウントする。

```text
/srv/teslamate/grafana-dashboards/vampire-drain.json
→ /dashboards/vampire-drain.json:ro
```

本番表示に問題がある場合は、このマウントだけを除去してGrafanaコンテナを再作成する。DBデータとTeslaMate本体は変更しないため、データ復旧は不要である。

PR作成後、Ansibleへ次の趣旨の英語コメントを追加する。

```python
# Temporary workaround for <PR URL>.
# Remove this patch after deploying an official TeslaMate Grafana image
# that contains the upstream fix.
```

PRがマージされた時点ではパッチを削除しない。修正を含む公式イメージを本番へ導入し、Vampire Drainの表示を確認してから削除する。

## 検証計画

### SQL単体検証

読み取り専用CTEで次のケースを検証する。

- 状態が駐車区間内に完全に収まる。
- 状態が開始境界をまたぐ。
- 状態が終了境界をまたぐ。
- 状態が両方の境界をまたぐ。
- `end_date IS NULL`である。
- 駐車区間が31日を超える。
- 状態レコードに重複がない場合、Standbyが0%から100%の範囲に収まる。

本番データでは現行SQLと修正SQLを並べて実行する。約98.4%の既知区間が修正され、約0.4%の区間が0%付近のままになることを確認する。完全内包された状態の既存結果は変わらないことも確認する。

### 性能と静的検証

TeslaMate開発ガイドに従い、修正クエリへ`EXPLAIN (ANALYZE, BUFFERS)`を実行する。現行クエリと実行計画、実行時間、読み取りブロック数を比較する。重大な性能退行や不適切な全表走査があれば、PR準備へ進まない。

Forkでは次を実行する。

- JSON構文検査
- `git diff --check`
- `treefmt`または`nix run .#lint`
- 環境を準備できる場合は`mix ci`

Ansibleでは次を実行する。

- パッチャーの単体テスト
- Composeテンプレート契約テスト
- Ansible syntax check
- `ansible-lint`

### 本番表示検証

1. Ansible check modeで予定差分を確認する。
2. 本番へ適用する。
3. Grafana APIからVampire Drainの読み込み済みクエリを取得し、修正を確認する。
4. browser-automationで90日表示を確認する。
5. 約98.4%区間が98%付近になることを確認する。
6. 約0.4%区間が0%付近のままであることを確認する。
7. パネル、リンク、期間変数、車両変数に回帰がないことを確認する。
8. Grafanaログにクエリエラーがないことを確認する。
9. Playbookを再実行し、変更が発生しないことを確認する。

## PRゲート

本番表示検証が完了するまでForkをcommitまたはpushしない。検証後にcommitとpushを行い、PRタイトルと本文を提示する。明示承認を得るまで`gh pr create`を実行しない。

PR本文には次を含める。

- 現象と原因
- 匿名化した再現値
- 半開区間とクリップ計算
- `age()`をtimestamp差へ変える理由
- テスト結果
- `EXPLAIN ANALYZE`の結果
- AI支援の開示

AI支援の開示はTeslaMate開発ガイドの形式に従う。

```markdown
---

🤖 Assisted by GPT-5.6-sol (OpenAI) via Kiro CLI (planning, implementation, testing, and PR description).
```

初回PRでCLA Assistantから要求された場合はFLA 2.0へ対応する。

## 完了条件

次を満たした時点で本作業を完了とする。

- SQL、性能、静的検証が成功している。
- 本番Grafanaで修正表示と非回帰を確認している。
- ユーザーがPRタイトルと本文を承認している。
- 上流PRを作成している。
- PR URLと廃止条件を記載した一時Ansibleパッチを本番へ適用している。

一時パッチの削除は別タスクとする。修正を含む公式Grafanaイメージを本番へ導入し、表示を確認してから削除する。
