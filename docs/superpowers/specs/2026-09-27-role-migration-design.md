# 既存ロールの移行 設計

## 背景と目的

リファクター全体の 4 サブプロジェクトのうち最後にあたる（全体は `2026-09-26-ansible-conventions-design.md` を参照）。

サブプロジェクト 1 で AGENTS.md の規約と見本ロール `filebrowser` を、2 で inventory と playbook の構成を、3 で更新方針を実装した。残る 40 ロール（tasks だけで約 9,000 行）は規約に合っておらず、`.ansible-lint-ignore` に 114 行が残る。9 つのロールがネストしたディレクトリにあり、ubuntu、raspberrypi、darwin は詰め合わせのロールになっている。前のサブプロジェクトから、毎回 changed になるタスク、check mode で失敗するタスク、レビューで見送った指摘も持ち越している。

目的は、全ロールを AGENTS.md の規約に合わせ、規約と実装のずれをなくすことである。

## 範囲

対象は全ロールと全 playbook である。ロールの改名、統合、格上げ、ファイルの分割に加えて、毎回 changed になるタスクと、持ち越した不具合を直す。

次の 3 つは例外として扱う。

- homeassistant は tasks、handlers、templates、vars、`tests/` を移行する。HA の YAML（`files/`）は別の HA YAML セッションが直しているため触らず、コミットされていない `tests/model_y_full_charge_due.yml` にも触らない。毎回 changed になる「Copy default file」も HA YAML セッションで直す
- darwin_business のホスト（`7cf34ded5d65.local`）は `connection: local` で、そのマシンでしか流せない。このため darwin_business 向けの変更は置き場所の移動と命名の整理に限り、動作を変えない。例外は Claude Code を toolbox の一覧に足す 1 行だけである。検証は syntax-check と lint までとし、実機での確認手順を完了報告に書く
- litellm と couchdb のポートを全インターフェースで公開している件は、動作が変わるため範囲外とし、別に相談する

## ロールの対応表

| 今 | 移行後 | 内容 |
|---|---|---|
| `database/client`、`database/client/gui` | `database_client`、`database_client_gui` | フラット化 |
| `homeassistant-ha/primary`、`homeassistant-ha/secondary` | `homeassistant_ha_primary`、`homeassistant_ha_secondary` | フラット化 |
| `postfix/client` | `postfix_client` | フラット化 |
| `zabbix/aws`、`zabbix/mcp`、`zabbix/money/market`、`zabbix/server` | `zabbix_aws`、`zabbix_mcp`、`zabbix_money_market`、`zabbix_server` | フラット化 |
| `zabbix/agent/ubuntu`、`zabbix/agent/raspberrypi`、`zabbix/agent/ec2` | `zabbix_agent` | 統合。`zabbix_agent_platform` で `tasks/<platform>.yml` を選ぶ |
| raspberrypi の `backup`、`restic-darwin` | `restic` | 統合。`ansible_facts['system']` で `tasks/linux.yml` と `tasks/darwin.yml` を選ぶ |
| ubuntu の `fail2ban` | `fail2ban` | 格上げ |
| raspberrypi の `network-failover`、`php-miio` | `network_failover`、`php_miio` | 格上げ |
| `darwin/personal` | 解体 | パッケージ一覧は inventory の `darwin_extra_*` に移し、treefmt は brew の一覧に入れる。nix は `nix` ロールに格上げする。Claude Code は削除する |
| `darwin/business` | 解体 | パッケージ一覧は inventory の `darwin_extra_*` に移す。toolbox、enfable、Kiro IDE（`axe`）、aim は `builder_toolbox` ロールにまとめ、Claude Code を toolbox の一覧に足す |

`darwin/personal` と `darwin/business` はホスト種別ごとのロールで、AGENTS.md の「種別の違いは inventory のデータか別のロールで表す」に反するため解体する。

Apache と HA secondary の監視の設定（UserParameter と zabbix-agent の再起動）は、監視される側と一緒に変わるため、それぞれ httpd と homeassistant_ha_secondary の `zabbix` コンポーネントに残す。

OS をまたぐツールのロールは作らない。Claude Code は darwin_business だけで使い、kiro-cli は ubuntu が公式のインストーラ、darwin_business が toolbox で入れていて、手順に共通する部分がない。uv、lightpanda、agent-browser などは Linux でだけインストーラで入れ、macOS では brew のパッケージ一覧に入っているため、OS ロールのコンポーネントに残す。

ほかのロールは名前を変えず、中をコンポーネントのファイルに分ける。変数の接頭辞と inventory のファイル名は移行後のロール名に合わせる。darwin の 2 つの playbook には play 名とロールのタグを付ける。

## Claude Code の削除

Claude Code は darwin_business でだけ使う。

- raspberrypi（fox、hotel）と darwin_personal（youth）から、インストールと更新のタスクを消す。代わりに legacy-removal タスクで `~/.local/bin/claude`、`/usr/local/bin/claude`、`~/.local/share/claude`、`~/.claude`、`~/.claude.json` を消し、全ホストが収束したらそのタスクも消す
- `~/.claude` は chezmoi が配っているため、chezmoi の `.chezmoiignore` で `.claude` と `.claude.json` を darwin_business 以外のホストでは配らないようにする。この変更は Ansible の削除より先に入れる。chezmoi のリポジトリへの変更は、差分を見せて承認を得てから push する
- darwin_business では `builder_toolbox` の `toolbox install` の一覧に `claude-code` を足し、更新は既存の `toolbox update` に任せる

## ロールごとの作業

各ロールを次のチェックリストに沿って移行し、そのロールの `.ansible-lint-ignore` の行を消す。

- `tasks/main.yml` には `import_tasks` だけを置き、コンポーネントごとに `tasks/<component>.yml` に分ける。タスク名は `<component> | 説明` にする
- タグはロール名、`<role>_<component>`、`update`、`always` の 4 種類だけにし、`install` や `config` などの操作のタグは消す
- 変数に接頭辞を付け、AGENTS.md の表に従って `vars`、`defaults`、inventory に置く。`register` と `set_fact` の結果は `__<role>_` で始める
- クォート、`mode: "0644"` の形、テンプレート先頭の `ansible_managed`、`debug` の `verbosity` をそろえ、`backup: true` を消す
- `command` と `shell` には理由のコメントと `changed_when` を付け、モジュールがあればモジュールに置き換える
- 前のサブプロジェクトで入れたものを含め、全ホストで収束した legacy-removal タスクを消す

## 持ち越した不具合の修正

| 対象 | 直し方 |
|---|---|
| postfix_client の SASL の db、mosquitto のパスワードファイル | 元のファイルが変わったときだけ handler で作り直す |
| ubuntu の 1Password debsig ポリシーと GitHub の GPG キー、couchdb の init スクリプト、power_monitor の設定 | 永続するパスに置いて `force` なしで取得し、中身が変わったときだけ changed にする |
| database_client_gui の corretto の `Update apt cache` | repo の定義を変えたときだけ更新する |
| raspberrypi の zabbix-agent の systemd ユニット | zabbix_agent への統合でテンプレートを 1 つにする |
| zabbix_money_market の「消してから clone」 | git モジュールだけで更新し、check mode でも失敗しないようにする |
| orascript | `/opt/orascript` に移し、実行時に参照するパスを合わせる。所有者の設定が毎回 changed になるのも直す |
| `aged_release` | エラーにリポジトリ名を入れる。タグと Release の一覧をページングする。イメージの作成日時をタイムゾーン付きで解析し、2000 年より前の日時はエラーにする |
| database_client の Oracle のディレクトリ選択 | `instantclient_*` がまだないホストでも check mode で失敗しないようにし、ディレクトリがなければ展開する |
| filebrowser、litellm、couchdb の restart handler | nvr や homeassistant と同じ check mode のガードを付ける |
| 片付け | `/usr/share/java` に残った古い Redshift の jar を消す。matter_server のデータのパス（`/etc/matter-server/data` と `/srv/matter-server/data`）のずれをそろえる |

## 波の分け方

spec は 1 本とし、plan は波ごとに書く。依存の少ないところから始め、影響の大きいものを後ろに回す。

| 波 | 対象 |
|---|---|
| 1. フラットな小さいロール | autodiscover、chezmoi、couchdb、desktop、docker、dsm、ec2、enecoq_data_fetcher、httpd、litellm、lmstudio、matter_server、mhz19、mosquitto、nvr、power_monitor、sslcert、syslogd、teslamate、udm |
| 2. フラット化と統合 | database_client、database_client_gui、homeassistant_ha_primary、homeassistant_ha_secondary、postfix_client、zabbix_agent、zabbix_aws、zabbix_mcp、zabbix_money_market、zabbix_server、orascript の移動 |
| 3. 格上げと OS ロール | fail2ban、network_failover、php_miio、restic、nix、builder_toolbox、darwin の 2 ロールの解体、Claude Code の削除、ubuntu、raspberrypi、darwin の分割、playbook のロールのアルファベット順への並べ替え |
| 4. 大きいサービス | nas、homeassistant |

`aged_release` の修正は、それを使うロールが最初に出てくる波 1 で行う。playbook の並べ替えは、改名がすべて終わった波 3 の最後に行う。

## 進め方と検証

波ごとにブランチを切り、ロールごとにコミットする。波の最後に fox、hotel、alfa、youth で `--check --diff` を流し、差分を見せて承認を得てから反映する。udm ロールを変えた波では sierra も同じ手順で扱う。反映後に 2 回目を流して `changed=0` を確かめ、main に fast-forward でマージして CI が通るのを確かめる。

改名、統合、分割はホスト上の状態を変えない。このため check の差分は、毎回 changed の修正と、意図した変更だけになるはずである。それ以外の差分は移行ミスとして直す。意図した変更は、orascript のパス、Claude Code の削除、統合で変わる handler 名の 3 つである。

restic と zabbix_agent は、systemd と launchd のユニット名、設定ファイルのパスを今のまま引き継ぎ、統合によってホストのファイルが作り直されないようにする。

## 完了条件

1. `.ansible-lint-ignore` がなくなり、CI の lint が通る。`roles/` にネストしたロールのディレクトリが残らない
2. fox、hotel、alfa、youth、sierra で、各 playbook 全体の `--check` がタスクを除外せずに exit 0 で終わる
3. 各 playbook 全体を 2 回流し、2 回目が `changed=0` になる。例外は homeassistant の「Copy default file」だけである
4. `darwin-business.yml` の syntax-check と lint が通り、実機での確認手順が完了報告にある
5. 規約を変えた箇所が AGENTS.md と README に反映されている

## 範囲外

- HA の YAML（`roles/homeassistant/files/`）と「Copy default file」（HA YAML セッション）
- litellm と couchdb のポートの公開範囲
- darwin_business の動作の変更（Claude Code の追加を除く）
