# Vampire Drain Standby SQL検証

## 判定

修正SQLは半開区間の境界ケース、本番実データ、性能基準をすべて満たした。全7行のStandbyは`0 <= standby <= 1`に収まり、現行SQLで欠落する境界横断状態を正しい重複秒数で集計した。修正SQLの実行時間中央値は現行比0.949倍、shared blockのhitとreadの合計中央値は1.000倍だった。PRへ進める判定とする。

## 検証条件

GrafanaのTeslaMate PostgreSQL datasource APIを管理セッションから読み取り専用で使用した。車両IDは本番値へ展開したが、本書では`<CAR_ID>`と表記する。期間は検証時点までの90日、最小駐車時間は6時間、航続距離は`rated`、距離単位は`km`とした。実時刻、ホスト名、位置、VINは記録していない。

現行SQLは`upstream/main`の`grafana/dashboards/vampire-drain.json`から取得した。修正SQLはforkの未コミット版から取得した。両JSONの`rawSql`に対し、次の変数展開を行った。

```text
$car_id = <CAR_ID>
$__timeFilter(start_date) = 90日間のUTC半開区間に対応する本番時刻条件
$duration = 6
${preferred_range} = rated
$length_unit / ${length_unit} = km
```

JSON構文検査は終了コード0だった。

```bash
git -C /path/to/teslamate show upstream/main:grafana/dashboards/vampire-drain.json > /tmp/vampire-drain-current.json
python3 -m json.tool /path/to/teslamate/grafana/dashboards/vampire-drain.json >/dev/null
```

## SQL差分

現行SQLは`age()`で駐車時間と状態時間を計算し、駐車区間へ完全に内包された状態だけを集計する。

```sql
EXTRACT(EPOCH FROM age(t.start_date, lag(t.end_date) OVER w)) AS duration

SELECT EXTRACT(EPOCH FROM sum(age(s.end_date, s.start_date))) AS sleep
FROM states s
WHERE state = 'offline'
  AND v.start_date <= s.start_date
  AND s.end_date <= v.end_date
  AND s.car_id = <CAR_ID>
```

修正SQLは駐車時間をtimestamp減算で計算し、状態区間と駐車区間の共通部分だけを加算する。判定は`[start_date, end_date)`の半開区間である。`asleep`と`offline`のLATERAL副問い合わせへ同じ変更を適用している。

```sql
EXTRACT(EPOCH FROM (t.start_date - lag(t.end_date) OVER w)) AS duration

SELECT EXTRACT(EPOCH FROM sum(
  LEAST(COALESCE(s.end_date, v.end_date), v.end_date)
  - GREATEST(s.start_date, v.start_date)
)) AS sleep
FROM states s
WHERE state = 'offline'
  AND s.start_date < v.end_date
  AND COALESCE(s.end_date, v.end_date) > v.start_date
  AND s.car_id = <CAR_ID>
```

Standbyの式は両SQLで次のとおりであり、修正後は分子と分母の両方が実経過秒になる。

```sql
(COALESCE(s_asleep.sleep, 0) + COALESCE(s_offline.sleep, 0)) / v.duration AS standby
```

## 合成境界ケース

本番datasource上で次の読み取り専用CTEを1回実行した。

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

結果は期待値と一致した。

| ケース | Standby | 判定 |
|---|---:|---|
| `contained` | 0.8 | PASS |
| `cross_both` | 1.0 | PASS |
| `cross_end` | 0.9 | PASS |
| `cross_start` | 0.9 | PASS |
| `open_end` | 0.9 | PASS |
| `thirty_one_days` | 1.0 | PASS |

## 本番実データ

状態が駐車区間の境界を横断する2区間を匿名化して比較した。秒数は状態区間と駐車区間の共通部分である。

| 区間 | 駐車時間 | offline | online | 修正Standby | 判定 |
|---|---:|---:|---:|---:|---|
| A | 69,445秒 | 68,314秒 | 1,131秒 | 0.984 | PASS |
| B | 28,422秒 | 104秒 | 28,318秒 | 0.004 | PASS |

修正SQLが返した全7行を検査し、全行が`0 <= standby <= 1`を満たした。現行SQLで97%から100%と表示される完全内包区間は6行あり、整数パーセントへの丸め表示は全6行で変わらなかった。

## 実行計画

両SQLへGrafana datasource API経由で次を3回ずつ実行した。

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
<expanded dashboard query>
```

| SQL | 実行時間3回 | 中央値 | shared hit + read 3回 | 中央値 |
|---|---|---:|---|---:|
| 現行 | 0.811 ms, 0.892 ms, 0.784 ms | 0.811 ms | 187, 187, 187 | 187 |
| 修正 | 0.770 ms, 0.762 ms, 0.773 ms | 0.770 ms | 187, 187, 187 | 187 |

修正SQLの実行時間中央値は現行比0.949倍、shared block中央値は1.000倍であり、どちらも2倍以内だった。現行・修正とも`states`へ条件付きSeq Scanが2個あり、修正SQLで個数は増えていない。各Scanには`state`、車両ID、区間境界のFilterがあり、無条件Seq Scanは0個だった。テーブル規模と実測コストに基づく既存プランであり、新しいインデックスは不要と判定した。

## セルフレビュー

- 半開区間の開始・終了横断、両端横断、`end_date IS NULL`、31日区間を個別に検証した。
- 本番クエリは`SELECT`、`WITH`、`EXPLAIN`だけを許可する二重の読み取り専用ガードを通した。SQL書き込みは実行していない。
- 実データの時刻、ホスト名、位置、VIN、資格情報を記録していない。
- 実行時間とshared blockは単発値ではなく3回の中央値で判定した。
- `states`アクセスは現行と修正を比較し、修正で無条件Seq Scanが追加されていないことを確認した。
