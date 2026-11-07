# calendar-mcp をやめて mailboxd に戻す 設計

## 目的

calendar-mcp は、Muse から iCloud のカレンダーと連絡先、Sakura のメールを一つの MCP サーバーで使うために、mailboxd を置き換えて入れた（`archive/specs/2026-11-07-calendar-mcp-design.md`）。その後、Muse はデバイスのアクセス権で iCloud のカレンダーと連絡先を直接読めるとわかった。calendar-mcp が要るのはメールだけになり、メールは mailboxd で足りる。

calendar-mcp を fox とリポジトリから取り除き、mailboxd を撤去前の形（`https://mail-mcp.rewse.jp/mcp`、ts、ubiqu、kyn の 3 メールボックス）に戻す。CloudFront と月次の pentest も mail-mcp に戻す。

## ゴール

- Muse から `https://mail-mcp.rewse.jp/mcp` で、撤去前と同じトークンで 3 人のメールボックスを使える
- fox に calendar-mcp のコンテナ、イメージ、設定、データ、vhost、fail2ban、ソースのチェックアウト、`calendar-mcp` アカウントが残らない
- `calendar-mcp.rewse.jp` は CloudFront、Route53、UniFi、Security Agent のどこにも残らず、`mail-mcp.rewse.jp` がそれぞれに戻る
- GitHub の fork `rewse/calendar-mcp` とローカルの clone を消す

## 範囲外

- mailboxd の監査ログとチェックポイント。撤去で `/srv/mailboxd` ごと消えたので、空から始まる
- docker ロールの buildx（calendar-mcp のために入れたが、残して困るものではない）と、`aged_release` のコミット選択（`2c16e9d5`）
- fox の Docker のビルドキャッシュ。calendar-mcp 以外のものも含むので触らない
- Muse 側のコネクタの切り替え、Apple ID の calendar-mcp 用 App 用パスワードの取り消し、1Password の calendar-mcp の項目の削除。どれも利用者が行う
- upstream（MarimerLLC/calendar-mcp）への pull request。fork と一緒にやめる

## 方針

各リポジトリで、撤去と置き換えのコミットを `git revert` で戻す。ansible-playbooks では a0aac483（mailboxd の撤去）を revert し、続く一つのコミットで `roles/calendar_mcp` を消して、fox からの片づけを mailboxd の legacy コンポーネントに置く。前回、calendar_mcp が mailboxd の片づけを持ったのと同じ形である。

- 採らない案: mailboxd のファイルを a0aac483^ から手で戻して新しいコミットにする。できるものは同じだが、何を取り消したのかが履歴から追えなくなる
- 採らない案: `roles/calendar_mcp` を片づけだけのロールとして残す。役目を終えたロールの名前が残り続ける

1Password の mailboxd トークン 3 件（`7tbut3qmtfp7dettl6hqsh6tei`、`pjplhxwrdrm25hob63i37iqdkm`、`b7wlevkrmcvdmd5x27wdzfgewu`）は、利用者が削除済みの項目から元の ID のまま戻した。mailboxd の変数は撤去前のまま使える。docker-mailbox は撤去後に新しいリリースがなく、`aged_release` は撤去前と同じ v0.8.0 を選ぶので、設定の形も変わらない（実装者の確認）。

## 設計

### ansible-playbooks

- a0aac483 の revert。mailboxd のロール、`home-primary.yml` の行、`tests/test_mailboxd.py`、`tests/test_fail2ban_apache.py` の一覧が戻り、`roles/calendar_mcp/tasks/legacy.yml` とその import が消える。衝突するのは `tests/test_calendar_mcp.py` だけで、次のコミットで消すファイルなので、legacy のテストを除いた形で解消する
- 続くコミットで `roles/calendar_mcp`、`tests/test_calendar_mcp.py`、`home-primary.yml` の calendar_mcp の行、`tests/test_fail2ban_apache.py` の `calendar_mcp` を消す
- 同じコミットで `roles/mailboxd/tasks/legacy.yml`（タグ `mailboxd_legacy`、`tasks/main.yml` の最後に import）を足す。英語のコメントで、mailboxd が calendar_mcp を置き換えたこと、全ホストが収束したらこのファイルと import を消すことを書く。順に次を行う
  - `/etc/compose/calendar_mcp/compose.yaml` があれば、Compose プロジェクトを止めてイメージごと消す（`state: absent`、`remove_images: all`）
  - .NET のベースイメージ `mcr.microsoft.com/dotnet/sdk:10.0` と `mcr.microsoft.com/dotnet/aspnet:10.0` を消す
  - vhost（`sites-enabled` と `sites-available` の `calendar-mcp.rewse.jp.conf`）を消して Apache を reload する
  - fail2ban の `filter.d/calendar_mcp.conf` と `jail.d/calendar_mcp.conf` を消して fail2ban を再起動する
  - `/etc/compose/calendar_mcp`、`/srv/calendar_mcp`、`/usr/local/src/calendar-mcp` を消す
  - `calendar-mcp` ユーザー、続いて同名のグループを消す（ファイルを消したあと）
- テストは `tests/test_mailboxd.py` に、legacy が calendar-mcp の上の各パスとアカウントだけを消し、mailboxd 自身のパスに触れないことを足す

### cloudfront-waf

b105d44（mail-mcp の停止）と 8e6520c（calendar-mcp の追加）を revert し、`AWS_PROFILE=cloudfront-waf-deploy scripts/deploy.sh` と `scripts/switch-dns.sh cloudfront` を実行する。`switch-dns.sh` は `calendar-mcp` の CNAME を消さないので、Route53 から手で消す。

### security-agent

a53977d（mail-mcp の pentest の停止）と 3fb6e6a（calendar-mcp の pentest の追加）を revert し、テンプレートを deploy する。mail-mcp の target domain は作り直しになるので、`_aws_securityagent-challenge.mail-mcp` の TXT を Route53 に置いて確認を通す。calendar-mcp の TXT は消す。

### UniFi

calendar-mcp の DNS ポリシー（`fb57fc89-e4bd-486f-9098-b788753e7fc7`）を消し、`mail-mcp.rewse.jp` を `fox.rewse.jp` に向ける CNAME のポリシーを `ttlSeconds: 0` で作る。

### 順番

1. ansible-playbooks を fox に適用する（mailboxd が上がり、calendar-mcp が消える）
2. cloudfront-waf を deploy し、DNS を切り替え、calendar-mcp の CNAME を消す
3. UniFi のポリシーを入れ替える
4. security-agent を deploy し、mail-mcp の target domain を確認し、calendar-mcp の TXT を消す
5. fox が fork を参照しなくなったので、GitHub の `rewse/calendar-mcp` とローカルの clone を消す

## 検証

- fox で mailboxd のコンテナが healthy で、calendar-mcp のコンテナ、イメージ、`.NET` のベースイメージ、上の各パス、`calendar-mcp` アカウントがない
- `mail-mcp.rewse.jp/mcp` が、家からも CloudFront 経由でも、トークンなしで 401、`calendar-mcp.rewse.jp` は名前解決しない
- 撤去前のトークン 1 件で MCP の `initialize` と `tools/list` が通る（値は表示しない）
- 2 回目の適用が `changed=0` になる
- Security Agent の mail-mcp の target domain が VERIFIED になる
- 各リポジトリのテストとリント、CI が通る
