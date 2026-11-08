# ペンテストの件数を Zabbix のホスト origin.rewse.jp に集める

## 目的

CloudFront 5xx トリガーの除外後の値は、fox と hotel のペンテストの件数を名指しで足している（`docs/superpowers/archive/specs/2026-11-08-cloudfront-5xx-exclude-security-agent-design.md`）。Zabbix 7.4.16 は foreach 関数に時間シフトを付けられないため、ホストを名指ししている。その結果、どちらかのホストに値がないと計算アイテムが unsupported になり、トリガーが今の式で判定するまで最大 30 分かかる。

hotel は Home Assistant のフェイルオーバー時に WAN の 443 を受けるホストで、普段はペンテストのリクエストを受けない。hotel の agent が止まっても、fox が受けたぶんだけで正しく差し引けるようにする。

## ゴールと非ゴール

ゴール:

- fox か hotel のどちらかの件数が届かなくても、計算アイテムが unsupported にならず、届いた件数で差し引く
- 両方の件数が届かないときは、今までどおり unsupported になり、今の式で判定する
- 切り替えのあいだも、ペンテストの除外を外さない

非ゴール:

- 件数の数え方、5 分枠の定義、トリガーの式を変えること

## 検討した方法

1. 両ホストが 1 組の trapper アイテムに送る（採用）: 同じ枠の値を fox と hotel が同じアイテムに入れ、計算式はそのアイテムの合計だけを見る。同じアイテムに同じ時刻の値が 2 つ入るため、ナノ秒をホストごとに変えて重複を避ける
2. ホストごとの計算アイテムで窓の合計を出し、alfa で `last_foreach` を足す: ホストごとの計算アイテムと alfa の計算アイテムが別々の時刻に評価されるため、窓がずれる
3. 送る値の時刻を B ではなく窓に入る時刻にずらし、時間シフトなしの foreach で足す: 送る時点で未来の時刻になり、値の意味が分かりにくい

受け手のホストには、alfa（CloudFront のテンプレートを持つ）と fox（普段の origin）も考えた。どちらもペンテストを受けるホストではなく、hotel の値が別のホストに入るねじれが残る。ユーザーは専用のホスト `origin.rewse.jp` を選んだ。CloudFront の origin 名と同じで、ルーターがそのときに転送する家の origin を表す。

## 設計

- Zabbix にホスト `origin.rewse.jp` を作る。インターフェースもテンプレートも持たず、グループは `Dummy hosts` にする。trapper アイテム `security_agent.requests` と `security_agent.errors.5xx`（Numeric unsigned）を直接持つ
- `security-agent-pentest-counts` の引数を `<log> <zabbix-host> <ns>` にし、`zabbix_sender -T -N` で `<zabbix-host> <key> <B> <ns> <value>` を送る
- UserParameter の conf をテンプレートにする。送り先は `httpd_security_agent_zabbix_host`（`vars/main.yml`、`origin.rewse.jp`）、ns は `inventory_hostname` の SHA-1 の先頭 7 桁（16 進）を整数にした値で、0 から 268435455 に収まり、fox と hotel で異なる
- alfa の計算アイテム 3 つの式のペンテスト部分を `sum(/origin.rewse.jp/security_agent.requests,15m:now-17m)` と `sum(/origin.rewse.jp/security_agent.errors.5xx,15m:now-17m)` に変える。CloudFront 側（`sum(//cloudfront.bucket.*,15m:now-17m)`）はすでに `now-17m` で、変えない
- `origin.rewse.jp` という名前のホストは Zabbix にまだない（2026-11-08 に `host.get` で確かめた）

## 切り替え

送り先を変えた瞬間から古いアイテムに値が届かなくなり、新しいアイテムに 3 枠たまるまで差し引きが足りなくなる。ペンテストは 2026-11-08 18:00 の時点でも続いているため、2 段階で切り替える（判断。ユーザーは方法を指定しておらず、除外を外さない側を選んだ）。

1. スクリプトが古い送り先（自ホストの `security_agent.*`）と `origin.rewse.jp` の両方に、1 回の `zabbix_sender -T -N` で送る版を適用する。古い送り先の行はホスト名に `-` を使う
2. `origin.rewse.jp` に 3 枠そろってから（適用の 35 分後以降）、計算アイテムの式を変える
3. 古い送り先に送らない版を適用し、テンプレート `MyTemplate App Apache CloudFront` の `security_agent.requests` と `security_agent.errors.5xx` を消す。`security_agent.sender` は残す

## 制約

- trapper アイテムの Allowed hosts は空のままにする（fox と hotel の両方から受ける）
- AGENTS.md の規約に従う。テンプレートは `{{ ansible_managed | comment }}` で始める
