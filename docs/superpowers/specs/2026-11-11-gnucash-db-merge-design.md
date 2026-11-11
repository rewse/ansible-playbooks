# gnucash データベースを rewse-pg に統合する

## 目的

Epoxy が 2026-11-10 に `gnucash-db-1c` の public access を強制的にオフにした(EpoxyMitigationsRisk-30057740)。private にするなら専用クラスタを持つ理由がないので、`gnucash` データベースを既存の Aurora PostgreSQL クラスタ `rewse-pg` に移し、`gnucash-db` クラスタ(`db.t3.medium` 1台)を廃止する。接続名は `rewse-pg.rewse.jp` に統一し、`gnucash-db.rewse.jp` は使わなくする。public access がなくなってオフィスから届かなくなったので、alfa を経由する SSH トンネルでつなげるようにする。

## 非目標

- データベースをインターネットに公開すること。オフィスからも SSH トンネルを経由してつなぐ。
- `rewse-pg` のパラメータ変更(`rds.force_ssl` など)。

## 制約

- 両クラスタとも Aurora PostgreSQL 16.11 で、KMS キーも同じ。`gnucash` データベースは 66 MB。
- RDS では `pg_authid` を読めないため、パスワードのハッシュは移せない。1Password にあるパスワードでロールを作り直す。
- 両クラスタとも自宅の site-to-site VPN か VPC 内からしか届かないので、作業は fox から行う。fox には psql 16.15 がある。
- バックアップ保持期間は両クラスタとも 35 日で、統合しても point-in-time restore できる期間は変わらない。
- expense.rewse.jp は、スマホのモバイル回線から使うため、IP の制限なしで CloudFront 経由で公開されている。gnucash-quick-expense はリクエストで受け取ったユーザー名とパスワードで、そのまま DB にログインする。ユーザー名の制限はない。パスワードが間違っていれば 401 を返すが、合っていても `gnucash` への CONNECT 権限がないロールだと 500 を返す。そのため、接続先を rewse-pg に変えると、インターネットから rewse-pg の全ロールのパスワードを試せて、正解かどうかもわかってしまう。
- alfa は同じ VPC の public サブネットにある EC2 で、SG がオフィスの IP からの SSH を許可している。オフィスの Mac から alfa と fox の両方に SSH でき、どちらからも `rewse-pg.rewse.jp:5432` に届くことを確かめてある。
- `rewse-pg` にはすでに `muse` ロールがあり、`gnucash-db` 側の `muse` とはパスワードが違う。

## 方式

採用するのは pg_dump と pg_restore。データが小さく利用者も一人なので、停止は数分で済む。論理レプリケーションを使えば止めずに移せるが、`gnucash-db` 側に専用のパラメータグループを作って再起動する必要があり、DMS も同程度の手間がかかる。Aurora のクローンは private サブネットに移すだけで、クラスタが減らないので統合にならない。

## 移行の中身

### ロール

`rewse-pg` に次のロールを作る。パスワードはクライアント側で SCRAM-SHA-256 の検証子にしてから `ALTER ROLE ... PASSWORD` で渡し、平文がサーバーのログに残らないようにする(実装者の判断)。

| ロール | パスワードの在りか | 備考 |
|---|---|---|
| `gnucash` | ansible vault `wypbfjrqxkssvefhycefqcfn5y` | データベースとテーブルの所有者。`postgres` を所有者として設定できるよう、`GRANT gnucash TO postgres` を実行する |
| `muse` | ansible vault `wi3josvnu5dujxoosdh74igisq` | 既存のロールをそのまま使う |
| `quick-expense` | Private vault `evpsfx7fz4g4c7xh23nvgr5eni` | 個人アカウントで読むため、1Password の承認が一回要る |

### expense フォームのユーザー名の制限

切り替えより前に、gnucash-quick-expense(`rewse/gnucash-quick-expense`)に許可するユーザー名の一覧を足す。一覧にない名前では DB に接続せず、パスワードが間違っているときと同じ 401 を返す。一覧は設定ファイルで受け取り、`roles/gnucash_quick_expense` の変数 `gnucash_quick_expense_db_users`(値は `quick-expense` だけ)から渡す。このリポジトリは自分のものなので、既定ブランチに入れれば `aged_release` の待ち時間なしで、home-primary を `--tags gnucash_quick_expense_app,gnucash_quick_expense_service` で適用すると反映される。expense.rewse.jp から `quick-expense` では入れて、ほかの名前では 401 になることを確かめてから、データの移行に進む。

### データ

1. fox の `gnucash-quick-expense` を止め、`gnclock` が空で、他の接続もないことを確かめる。
2. fox で、`gnucash` ロールとして `gnucash-db` から `pg_dump -Fc -C` を取る。データベースの CONNECT 権限(`gnucash`、`muse`、`quick-expense`)と、テーブルの権限もダンプに含まれる。
3. `rewse-pg` に `postgres` として `pg_restore -C` で入れる。
4. 全テーブルの件数、`transactions` の最新 `enter_date`、権限を新旧で比べる。
5. `gnucash-db` クラスタを停止し、古い接続先に書き込まれないようにする。
6. Route53 から `gnucash-db.rewse.jp` の CNAME を消す。

### クライアント

- ansible vault `wypbfjrqxkssvefhycefqcfn5y` の `server` を `rewse-pg.rewse.jp` にし、タイトルを `PostgreSQL - gnucash` に変える。そのうえで、home-primary を `--tags gnucash_quick_expense_service` で適用する。
- `roles/muse` の `muse_pgpass_entries` から `gnucash-db.rewse.jp` を外す。lineinfile は一覧にある行しか管理しないので、`pgpass.yml` の最後に古い行を消すタスク(`state: absent`)を足し、home-primary と home-secondary を `--tags muse_pgpass` で適用する。全ホストに反映したら、そのタスクは消す。
- ansible vault `bfw2z4gziah6gnt44v7hl7k22q`(gnucash-db 用の muse)をアーカイブする。
- gnucash vault `n4k5eoi3jxo7ynmsfxisls7liu` の `server` を `rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com` にし、タイトルを `PostgreSQL - gnucash` に変える。`verify-full` で接続するので、Aurora のエンドポイント名を入れる。
- gnucash-import-agent の `SKILL.md` で、`op://gnucash/gnucash-db/...` を `op://gnucash/n4k5eoi3jxo7ynmsfxisls7liu/...` に変える。今のタイトルは `gnucash-db` と一致しないので、この参照は現在読めていない。あわせて、「オフィスからはインターネット経由で接続」の記述を下の「オフィスからの接続」に合わせて直し、トンネル越しに `verify-full` で接続する書き方を足す。
- 各 Mac の GnuCash は、利用者が `postgres://gnucash@rewse-pg.rewse.jp/gnucash` で開き直す。オフィスでは下のトンネルを使い、`postgres://gnucash@localhost:15432/gnucash` で開く。Muse のコネクタやプロンプトが `gnucash-db.rewse.jp` を名指ししていれば、それも利用者が直す。

### オフィスからの接続

chezmoi の `private_dot_ssh/config.tmpl` の `Host alfa` に `LocalForward 15432 rewse-pg.rewse.jp:5432` を足し、`chezmoi apply` する。`ssh -N alfa` を実行している間、Mac の `127.0.0.1:15432` が `rewse-pg` につながる。`LocalForward` は既定でループバックだけで待ち受けるので、Mac の外には公開されない。

psql で `verify-full` を使うときは、`host` に Aurora のエンドポイント名、`hostaddr` に `127.0.0.1`、`port` に `15432` を指定する。libpq は証明書の検証に `host` を使い、接続に `hostaddr` を使うので、トンネル越しでも検証が通る。

トンネルは必要なときに手で張る。常時張っておく仕組み(launchd や autossh)は作らない(実装者の判断)。

### 旧クラスタ

切り替えのときに最終スナップショットを取ってから止める。止めたまま残しておき、利用者が GnuCash と expense フォームで動作を確かめたら、削除保護を外して消す。停止中のクラスタは設定を変えられないので、削除保護を外す前に一度起動する。削除の前には改めて確認する。最終スナップショットは手動スナップショットなので、利用者が消すまで期限なしで残る。SG の `default` とパラメータグループの `default.aurora-postgresql16` は rewse-pg と共用なので残す。サブネットグループの `general pub` は使われなくなるが、費用はかからないので残す(実装者の判断)。Aurora は停止から 7 日で自動的に起動するので、それまでに消すか、もう一度止める。

## 実装者に任せること

- コマンドの細部(pg_dump と pg_restore のオプション、待ち方、比較の SQL)。
- AWS への書き込みは、このホスト(`7cf34ded5d65`)の `admin` プロファイルで行う。
