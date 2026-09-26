# inventory と playbook 構造の刷新 設計

## 背景と目的

リファクター全体の 4 サブプロジェクトのうち 2 つ目にあたる（全体は `2026-09-26-ansible-conventions-design.md` を参照）。

現状では 1 台のホストが複数の playbook に属する。fox は `ubuntu.yml`、`raspberrypi.yml`、`singleton_int1.yml` の 3 本で構成され、`site.yml` がそれらを順に流す。`singleton_ext1`、`singleton_int1`、`singleton_int2` はどれも 1 台だけのグループで、実質はホスト固有の値の置き場になっている。変数にはロール名の接頭辞がなく（`local`、`location`、`ssh_port`）、どこからも参照されない値（`local.fqdn`、`zabbix.server`）も残っている。inventory はルート直下の ini ファイル 1 本で、`host_vars` はない。

目的は、CoP 2.2 と 7.3 に沿って、ホストの type ごとに playbook を 1 本にし、inventory をディレクトリに構造化することである。成功の条件は次のとおり。

- どのホストも、その type の playbook を 1 本流せば設定が揃う
- 変数の置き場所と名前が AGENTS.md の規約に従う
- どのホストの設定内容も変わらない

管理対象は現在の 6 台（fox、hotel、alfa、sierra、Mac 2 台）から増えない前提とする。

## type と playbook

type の名前には、ホスト名ではなく役割名を使う。playbook のファイル名はハイフン区切りとし、inventory のグループ名は同じ名前をアンダースコアでつなぐ。

| ホスト | 旧グループ | 新しい playbook | 新しいグループ |
|---|---|---|---|
| fox.rewse.jp | `singleton_int1` | `home-primary.yml` | `home_primary` |
| hotel.rewse.jp | `singleton_int2` | `home-secondary.yml` | `home_secondary` |
| alfa.rewse.jp | `singleton_ext1` | `cloud-workstation.yml` | `cloud_workstation` |
| sierra.rewse.jp | `udm` | `udm.yml`（変更なし） | `udm` |
| Mac 2 台 | `darwin_business` / `darwin_personal` | `darwin-business.yml` / `darwin-personal.yml`（変更なし） | 変更なし |

`ubuntu.yml`、`ec2.yml`、`raspberrypi.yml`、`singleton_ext1.yml`、`singleton_int1.yml`、`singleton_int2.yml` は削除する。`site.yml` は `home-primary.yml`、`home-secondary.yml`、`cloud-workstation.yml` を `import_playbook` で読み込む。対象ホストは現状と同じである。

### playbook の中身

各 playbook は現状の複数 playbook のロールを 1 つの play にまとめ、層の順（OS、プラットフォーム、複数 OS 共通のツール、サービス）に並べる。層の中はアルファベット順とする。`hosts`、`become: true`、`remote_user` は現状の値を引き継ぐ。

| playbook | OS | プラットフォーム | 共通ツール | サービス |
|---|---|---|---|---|
| `home-primary.yml` | `ubuntu` | `raspberrypi` | `chezmoi`、`postfix/client`、`zabbix/agent/ubuntu`、`zabbix/agent/raspberrypi` | `mhz19`、続けて現在の `singleton_int1.yml` のロールを現在の順で |
| `home-secondary.yml` | `ubuntu` | `raspberrypi` | `chezmoi`、`postfix/client`、`zabbix/agent/ubuntu`、`zabbix/agent/raspberrypi` | `mhz19`、続けて現在の `singleton_int2.yml` のロールを現在の順で |
| `cloud-workstation.yml` | `ubuntu` | `ec2` | `chezmoi`、`postfix/client`、`zabbix/agent/ubuntu`、`zabbix/agent/ec2` | 現在の `singleton_ext1.yml` のロールを現在の順で |

- `zabbix/agent/raspberrypi` と `zabbix/agent/ec2` は `zabbix/agent/ubuntu` の設定を上書きするので、アルファベット順の例外として `zabbix/agent/ubuntu` の後に置く。この例外はサブプロジェクト 4 で `zabbix_agent` に統合するときになくなる
- 現在は `ubuntu.yml` の全ロールが `raspberrypi.yml` より先に流れるが、新しい順では `raspberrypi` が `chezmoi` と `postfix/client` より先になる。これらは互いの設定に触れないため影響はない想定で、検証の check で確かめる
- サービスの層は、現在の実行順を保つため旧 playbook の順に並べ、アルファベット順への並べ替えはサブプロジェクト 4 で行う。`mhz19` は旧 `raspberrypi.yml` にあり旧 `singleton_*.yml` より先に流れていたため、サービスの先頭に置く
- 各ロールには playbook 側でロール名のタグを付ける。ネストしたロールには、サブプロジェクト 4 で使うフラットな名前（`postfix_client`、`zabbix_agent`、`zabbix_server` など）を先に付け、後でタグ名が変わらないようにする。`zabbix/agent/*` はすべて `zabbix_agent` とする
- play には `Configure home primary` のように命令形の名前を付ける

ネストしたロールの参照は `role-name[path]` に当たる。これはファイル名が変わるだけの既存の違反なので、`.ansible-lint-ignore` の該当行を新しいファイル名に付け替える。

## inventory

`inventory/` ディレクトリに移し、`ansible.cfg` の `inventory` を `inventory` にする（CoP 7.3）。

```
inventory/
  hosts
  group_vars/
    all/
      site.yml
  host_vars/
    alfa.rewse.jp/
      ansible.yml
      ec2.yml
    fox.rewse.jp/
      ansible.yml
      mhz19.yml
      raspberrypi.yml
    hotel.rewse.jp/
      ansible.yml
      mhz19.yml
      raspberrypi.yml
```

`inventory/hosts` は ini 形式のままとし、変数は書かない。グループは type グループ（`home_primary`、`home_secondary`、`cloud_workstation`、`darwin_business`、`darwin_personal`、`udm`）と、アドホック実行用の `ubuntu`、`raspberrypi`、`ec2` とする。ルートの `hosts` と `group_vars/` は削除する。

変数ファイルは、読むロールごとに `<role>.yml` に分ける。`ansible.yml` は接続に関わる変数（`ansible_port` など）だけに使う。`group_vars/all/site.yml` には AGENTS.md に一覧のある共有値だけを置く。

### 変数の移し先

| 旧 | 読むロール | 新 |
|---|---|---|
| `ssh_port` | ubuntu（`sshd.conf.j2`）、raspberrypi（`override.conf.j2`） | `host_vars/<host>/ansible.yml` の `ansible_port`。両テンプレートは `ansible_port` を読む |
| `local.ip` | raspberrypi（`99-config.yaml.j2`） | `host_vars/<host>/raspberrypi.yml` の `raspberrypi_primary_address` |
| `local.ip_2` | raspberrypi（`99-config.yaml.j2`） | `host_vars/<host>/raspberrypi.yml` の `raspberrypi_secondary_address` |
| `local.fqdn` | なし | 削除 |
| `location` | mhz19（`mhz192mqtt.j2`） | `host_vars/<host>/mhz19.yml` の `mhz19_location` |
| `secondary_diskname` | ec2（`tasks/main.yml`） | `host_vars/alfa.rewse.jp/ec2.yml` の `ec2_secondary_disk` |
| `zabbix.server` | なし | 削除 |
| `admin`、`email`、`global_ip`、`ipv6`、`supply_chain_cooldown_days` | 複数 | `group_vars/all/site.yml`（名前は変えない） |

`ssh_port` を `ansible_port` にまとめるのは、sshd が待ち受けるポートと Ansible が接続するポートが常に同じ値だからである。これで Ansible は `~/.ssh/config` に頼らずに接続でき、値の置き場所が inventory の 1 箇所になる。ポートを変えるときは、新旧両方で待ち受ける状態を作ってから `ansible_port` を切り替える。

値の中身は変えない。

## ドキュメント

AGENTS.md に次を反映する。

- Role Design: playbook は type ごとに 1 本で、名前は役割名をハイフンでつなぐ。inventory のグループ名は同じ名前をアンダースコアでつなぐ
- Variables: inventory は `inventory/` に置き、変数ファイルは `group_vars/<group>/<role>.yml` と `host_vars/<host>/<role>.yml` にする。`ansible.yml` は接続まわりの変数専用、`group_vars/all/site.yml` は共有値専用とする

README の Project Structure、Inventory、実行例（`ubuntu.yml` などを使う例）を新しい構成に合わせる。

## 移行と検証

切り替えは 1 回のコミットで行う。設定の中身は変わらないので、前後の inventory と check mode の結果を比べて同一性を示す。

1. main の状態で基準を取る
   - 6 台分の `ansible-inventory --host <host>` の出力。Secret Reference は lookup の文字列のまま出力され、秘密の値は解決されない
   - fox、hotel、alfa のそれぞれで、現在属する playbook（fox なら `ubuntu.yml`、`raspberrypi.yml`、`singleton_int1.yml`）を `--limit` 付きの `--check --diff` で流した結果
2. 切り替え後に確かめる
   - inventory の出力を jq で上の対応表に沿って読み替えると基準と一致する。`local.fqdn` と `zabbix.server` はなく、`ansible_port` がある
   - 新しい playbook の `--check --diff` で変更を報告するタスクの集まりが、基準と同じになる。apt の upgrade や cooldown による新しいイメージなど実行時に変わる変更は基準にも同じく出るので、比較から切り分けられる
   - 全 playbook の `--syntax-check` と `pre-commit` が通る
3. check mode で同一と確かめられたら、本番には反映しない。次の通常の実行で反映される

darwin 2 台と sierra は playbook を変えないので、inventory の出力の一致だけを確かめる。

プレイブックの成否はプロセスの終了コードで判断する。

## 完了条件

- 6 台すべての inventory の出力が、対応表に沿って基準と一致する
- fox、hotel、alfa で、新しい playbook の check の結果が基準と同じになる
- 全 playbook の `--syntax-check` と、CI の Ansible Lint が通る
- `singleton` を含むファイル名、グループ名、変数名がリポジトリに残っていない（`docs/` の過去の spec と plan を除く）

## 範囲外

- ロールのフラット化と改名、`zabbix/agent/*` の統合（サブプロジェクト 4）
- `docker/quarantine` の一般化と compose のプロジェクト分割（サブプロジェクト 3）
- `~/.ssh/config` の変更
