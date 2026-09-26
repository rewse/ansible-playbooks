# 更新方針の実装 設計

## 背景と目的

リファクター全体の 4 サブプロジェクトのうち 3 つ目にあたる（全体は `2026-09-26-ansible-conventions-design.md` を参照）。

AGENTS.md の Update Policy は、サードパーティのものを公開から `supply_chain_cooldown_days` 日以上たった最新版に実行時に解決すると定めている。しかし実装はこの方針に追いついていない。コンテナイメージは `docker/quarantine` ロールが対象ホスト上の skopeo で解決するが、呼び出し側に `include_role`、`apply.tags`、空値のガードが要り、filebrowser ではタグの漏れと未定義変数の不具合が出た。git と GitHub Release は vars にバージョンを手書きし、手で上げている。HA のカスタムコンポーネントは `/tmp` に dry-run の git でチェックアウトするため、check mode で必ず失敗する。compose は全ロールが共有の `/etc/compose.yml` に `blockinfile` で書き込み、プロジェクト名は `etc` になっている。

目的は、更新方針を 1 つの仕組みで実装し、vars にバージョンを書いて手で上げる作業をなくすことである。成功の条件は次のとおり。

- 理由のコメント付きの定数を除き、vars にバージョンが残らない
- check mode がタスクを除外せずに最後まで流れる
- 2 回目の実行で `changed=0` になる

## 範囲

### 対象と cooldown

| 対象 | cooldown | 仕組み |
|---|---|---|
| apt、brew | なし | 既存の OS ロールの `upgrade.yml` |
| GitHub 以外の配布元、公式のインストーラ | なし | 配布元の最新版の URL、apt、各ツールの自己更新 |
| npm、PyPI | `supply_chain_cooldown_days` 日 | chezmoi が管理する npmrc と uv.toml |
| コンテナイメージ、GitHub の git と Release（HA の git コンポーネントを含む） | `supply_chain_cooldown_days` 日 | lookup プラグイン `aged_release` |
| 自分のリポジトリとパッケージ | なし | デフォルトブランチを追う、または cooldown の除外設定 |

### ロールへの手の入れ方

このサブプロジェクトでは、各ロールのバージョン解決、compose、配置のタスクだけを直す。タスク名、タグ、ファイル分割、ロール名のフラット化はサブプロジェクト 4 で行い、`.ansible-lint-ignore` の既存の行は残す。新しく書くタスクは ignore なしで lint を通す。動作を変える変更（本サブプロジェクト）と動作を変えない整理（サブプロジェクト 4）を分け、それぞれの検証を単純にするためである。

## lookup プラグイン `aged_release`

### 配置

- 本体: `plugins/lookup/aged_release.py`。`ansible.cfg` に `lookup_plugins = plugins/lookup` を足す
- テスト: `tests/test_aged_release.py`（pytest）。`skopeo` と `gh` の呼び出しを差し替える

コントローラー（実行する Mac）で動き、`skopeo` と `gh` を subprocess で呼ぶ。レジストリごとの認証やマニフェストの違いは skopeo に、GitHub の認証と回数制限は `gh` のトークンに任せ、プラグイン本体は絞り込み、並べ替え、cooldown の判定だけを持つ。skopeo は darwin ロールのパッケージ一覧に足す。

### 呼び出しと戻り値

| 呼び出し | 戻り値 |
|---|---|
| `lookup('aged_release', 'oci:<registry>/<repo>', platform='linux/arm64')` | `{version, ref}`。`ref` は `<registry>/<repo>:<tag>@<digest>` |
| `lookup('aged_release', 'github-release:<owner>/<repo>', asset='<file name>')` | `{version, url, checksum}`。`checksum` は `sha256:<hex>`、取れないときは空文字 |
| `lookup('aged_release', 'github-tag:<owner>/<repo>')` | `{version, commit}` |
| `lookup('aged_release', 'github-commit:<owner>/<repo>')` | `{commit}` |

共通の引数:

- `pattern`: 対象にするタグの正規表現。既定は `'^v?\d+(\.\d+)*$'`
- `days`: cooldown の日数。既定は変数 `supply_chain_cooldown_days`

`asset` にはバージョンを含むファイル名のために `{version}` を書ける（例: `restic_{version}_linux_arm64.bz2`）。

### 公開日と固定の値

| 種類 | 公開日 | 除外 | 固定の値 |
|---|---|---|---|
| `oci` | イメージの `created` | `pattern` に合わないタグ | `tag@digest`（`platform` のマニフェスト） |
| `github-release` | Release の `published_at` | draft、prerelease、`pattern` に合わないタグ | タグとファイルの sha256（GitHub API の `digest`） |
| `github-tag` | タグが指すコミットのコミット日時 | `pattern` に合わないタグ | コミットの SHA |
| `github-commit` | デフォルトブランチのコミット日時 | なし | 公開から `days` 日以上たったうち最新のコミットの SHA |

タグは数値部分で比較して新しい順に並べ、公開から `days` 日以上たった最初のものを選ぶ。タグの付け直しで中身が差し替わっても受け入れないよう、digest、sha256、SHA で中身を固定する。`github-release` でファイルの `digest` がないときは、タグだけで固定し、その旨を `verbosity` 付きの表示で出す。

### 振る舞い

- 同じ引数の呼び出しは、1 回の実行の中でキャッシュして使い回す
- check mode でも値を返す
- 条件に合う版がないとき、または skopeo や `gh` が失敗したときは、lookup をエラーにしてタスクを失敗させる。空値を返してガードで skip する方式は、呼び出し側のガード漏れと古い値の使い回しを招くため採らない。GitHub やレジストリに届かないときは、後で流し直す。`force_handlers` により、途中で止まっても通知済みの handler は流れる

### 呼び出し側

解決した値は `set_fact` で `__<role>_<component>` に入れ、同じ component の後続タスクから参照する。`set_fact` は実行時に求める値にだけ使うという規約に沿う。

```yaml
- name: container | Resolve aged image
  ansible.builtin.set_fact:
    __filebrowser_image: "{{ lookup('aged_release', 'oci:ghcr.io/gtsteffaniak/filebrowser', pattern='^\\d+\\.\\d+\\.\\d+-stable$', platform='linux/arm64') }}"
```

`platform` は対象ホストの fact（`ansible_facts['architecture']`）から求める。

## compose

### ロールごとのプロジェクト

- 各ロールは `/etc/compose/<role>/compose.yaml` を `template`（`compose.yaml.j2`）で丸ごと持つ。先頭に `name: <role>` を書く。秘密の値を含むものは `mode: "0640"` とする
- ファイル名は Docker の推奨に合わせて `compose.yaml` とする。リポジトリの `.yml` の例外である
- イメージは `image: {{ __<role>_image.ref }}` とする
- 起動は `community.docker.docker_compose_v2` で `project_src: /etc/compose/<role>`、`state: present`、`pull: missing` とする。compose ファイルの変更は `state: present` がコンテナを作り直すので、イメージの更新に handler は使わない。restart の handler はマウントした設定ファイルが変わったときだけに使い、`pull: always` と `recreate: always` はやめる
- ネットワークは各プロジェクトの既定のものを使う。HA と Matter は `network_mode: host` のまま、ほかは `127.0.0.1` の公開ポートのままとする。プロジェクトをまたぐサービス名の参照はない（fox で確認済み）

データは今どおり `/srv/<role>` に置く。

### 旧プロジェクトからの切り替え

各ロールの container コンポーネントで、起動より前に次を流す。

1. 同じ名前のコンテナが旧プロジェクト（ラベル `com.docker.compose.project=etc`）に属していれば削除する（`community.docker.docker_container_info` で確かめ、`community.docker.docker_container` の `state: absent` で消す）
2. `/etc/compose.yml` からそのロールのブロックを `blockinfile` の `state: absent` で消す

名前の衝突を避けるため、並び順の規約の例外として起動の前に置き、理由をコメントに書く。全ホストの切り替えが終わったら、この 2 つのタスクは削除する。

### docker ロールと docker_quarantine

- docker ロールの `/etc/compose.yml` を作るタスク（`touch` と `services:` の行）を、`/etc/compose` ディレクトリを作るタスクに置き換える
- すべてのロールの切り替えが終わったら、`/etc/compose.yml` を `state: absent` で消す
- `docker/quarantine` ロールと `docker_quarantine_days` を削除する。filebrowser の `# noqa: role-name[path]` と `apply.tags` もなくなる

teslamate の独自の解決も lookup に置き換える。

## git と GitHub Release

### 置き場所

| 用途 | 置き場所 |
|---|---|
| インストールのためにチェックアウトして別の場所へコピーするソース | `/usr/local/src/<name>` |
| チェックアウトの場所から動かすソフトウェア | `/opt/<name>` |
| サービスのデータ | `/srv/<role>` |

FHS 3.0 の用途に従う。`/srv` はホストが提供するデータの場所で、チェックアウトは置かない。

### git（他人のリポジトリ）

- lookup の `commit` を `ansible.builtin.git` の `version` に渡し、`/usr/local/src/<name>` にチェックアウトする
- そこから `ansible.builtin.copy`（`remote_src: true`）で配置先にコピーする。check mode でチェックアウトがまだないときはコピーを skip し、理由を表示する
- 旧いチェックアウト（`/tmp/<name>`、`/srv/git/<name>`）を `state: absent` で消す

対象は HA の frigate、frosted-glass-manager、hems_echonet_lite、tuya-local、frosted-glass-themes、card-mod と、php-miio、ssl-cert-check、one-gnome-terminal。zabbix_mcp はその場所から動かすため `/opt/zabbix-mcp/src` のままで、`version` だけを lookup にする。

自分のリポジトリ（stock-price-fetcher、orascript）は変えない。orascript の `/opt/orascript` への移動は、実行時に参照するパスも変わるためサブプロジェクト 4 で行う。

### GitHub Release のファイル

`ansible.builtin.get_url` に lookup の `url` を渡し、`checksum` が空でなければ `checksum` も渡す。対象は HA の mini-graph-card、mini-media-player、simple-thermostat、simple-weather-card、lightpanda、restic、power_monitor、Source Han Mono / Sans / Serif、Redshift JDBC（`aws/amazon-redshift-jdbc-driver`）。各ロールの vars の対応する `_version` を消す。

## GitHub 以外の配布元

cooldown なしで最新版にする。

| 対象 | やり方 |
|---|---|
| Oracle Instant Client | 最新版の固定 URL（`instantclient-<package>-linux-arm64.zip`、x86_64 は `linuxx64`）を `unarchive` する。展開先のディレクトリ名（`instantclient_<major>_<minor>`）はバージョンで変わるので、展開後に `find` で求めて参照する |
| AWS SCT | 既存の `aws-schema-conversion-tool-1.0.latest.zip` を使う。中の deb はバージョン付きの名前なので、展開後に `find` で求めて入れる |
| MySQL の apt 設定 | 最新版の固定 URL `https://repo.mysql.com/mysql-apt-config.deb` で入れる。以後は apt に任せる |
| MySQL Connector/J | MySQL の apt リポジトリの `mysql-connector-j` パッケージを apt で入れる。パッケージの存在は実装時に確かめ、ない場合はこの行を見直す |
| `httpd_php_version` | Ubuntu が配布する PHP のメジャーバージョンなので固定ではない。`roles/httpd/vars/ubuntu.yml` の定数にし、Ubuntu の版に従う旨をコメントに書く |
| Corretto（`database_corretto_version`） | 現在の LTS（25）の定数とし、DBeaver と SCT が動く Java の版に合わせる旨をコメントに書く。パッケージ自体は apt で最新になる |
| `raspberrypi_netgear_gs108tv3_version` | 参照がないので削除する |

Oracle と SCT は、URL がすべて HTTP 200 を返すことを 2026-09-27 に確かめた。Redshift JDBC の `latest` の URL は 403 だったため、GitHub Release に切り替える。

## npm と uv

- npm と uv の cooldown は chezmoi リポジトリ（`rewse/chezmoi`）が持つ。ふだんの手動のインストールと Ansible からの実行で同じ設定を使うためである
- chezmoi の `dot_config/npm/npmrc` に `min-release-age=4` を足す。自分のパッケージがあれば `min-release-age-exclude` で外す
- chezmoi の `dot_config/uv/uv.toml` は既に `exclude-newer = "4 days"` を持つ。`enecoq-data-fetcher` は自分のパッケージなので、`exclude-newer-package` で cooldown から外す
- npm は `NPM_CONFIG_USERCONFIG` がないと `~/.config/npm/npmrc` を読まない。この環境変数は `.zshenv` で設定されており、Ansible の実行では読まれない。npm を動かすタスクには `environment` で `NPM_CONFIG_USERCONFIG: "{{ ansible_env.HOME }}/.config/npm/npmrc"` を渡す
- chezmoi の日数は `supply_chain_cooldown_days` と揃える。この対応を AGENTS.md に書く

## 公式のインストーラ

ツールは、配布元が公式に案内するインストール方法を優先して入れる（公式の apt リポジトリ、Homebrew、インストーラのスクリプトなど）。サードパーティのパッケージや独自の手順は、公式の方法がその OS やプラットフォームで使えないときだけ使い、理由をコメントに書く。公式の方法に従うと、配布元の更新の仕組みや署名の検証をそのまま使える。既存のタスクがこれに反している場合の置き換えはサブプロジェクト 4 で行う。

uv、kiro-cli、Claude Code、nix、deno、zinit は、インストール後も `update` タグの component で各ツールの自己更新を流して最新版を保つ（`uv self update`、`claude update`、`deno upgrade` など）。kiro-cli、nix、zinit の更新コマンドは実装時に確かめる。`command` を使う理由と `changed_when` は規約どおり書く。

## 進め方

1. lookup プラグインを作り、pytest を通す
2. chezmoi の npmrc と uv.toml を直す（別リポジトリへの書き込みのため、実行前にユーザーの確認を取る）。Ansible の npm のタスクに `NPM_CONFIG_USERCONFIG` を渡す
3. compose をロールごとに切り替える。順は filebrowser、litellm、couchdb、teslamate、nvr、matter_server、homeassistant（fox）、homeassistant-ha/secondary（hotel）。Matter と HA は続けて行う。各ロールの反映はユーザーの確認を取ってから行う。最後に docker ロールを直し、`/etc/compose.yml` と `docker/quarantine` を消す
4. git と Release を lookup に置き換える。HA のコンポーネント、ubuntu、raspberrypi、darwin、power_monitor、zabbix、desktop、database の順
5. GitHub 以外の配布元とインストーラを最新版にする
6. AGENTS.md と README を直す

## 検証

- lookup: pytest で、パターンでの絞り込み、バージョンの並べ替え、cooldown の境目（ちょうど `days` 日）、draft と prerelease の除外、digest がないとき、解決できないときのエラー、同じ呼び出しのキャッシュを確かめる
- ロールごとの反映: `--check --diff` で差分を見てから反映し、続けて同じ条件でもう一度流して `changed=0` を確かめる。コンテナが healthy であること、公開している HTTPS が 200 を返すこと、HA のエンティティが復帰することを確かめる。バージョンが上がる差分は想定どおりの変化として中身を見て判断する
- HA の check mode: fox で `home-primary.yml --check` が、`custom`、`theme`、`lovelace` を除外せずに終了コード 0 で流れる
- 全体: fox、hotel、alfa、Mac で type ごとの playbook を流し、2 回目が `changed=0` になる。pre-commit と CI が通る

プレイブックの成否はプロセスの終了コードで判断する。

## ドキュメント

AGENTS.md に次を反映する。

- Update Policy: 解決は `aged_release` の lookup で行い、digest、sha256、SHA で固定する。npm と uv の cooldown は chezmoi が持ち、日数を `supply_chain_cooldown_days` と揃える。GitHub 以外の配布元とインストーラは固定せず最新版にする
- インストール方法: 配布元の公式のインストール方法を優先し、使えないときだけ別の方法を使って理由をコメントに書く
- 置き場所: `/usr/local/src/<name>`、`/opt/<name>`、`/srv/<role>`、`/etc/compose/<role>/compose.yaml`
- filebrowser を新しい形に直し、引き続き見本とする

README の実行例とプロジェクト構成に `plugins/` を足す。

## 完了条件

- vars にバージョンが残っているのは、理由のコメントが付いた定数（Corretto、PHP）だけになる
- `docker/quarantine`、`/etc/compose.yml`、`/tmp` と `/srv/git` の他人のリポジトリのチェックアウトがなくなる
- fox の check mode が、タスクを除外せずに終了コード 0 で流れる
- fox、hotel、alfa、Mac で 2 回目の実行が `changed=0` になる
- pytest、pre-commit、CI が通る

## 範囲外

- タスク名、タグ、ファイル分割、ロール名のフラット化（サブプロジェクト 4）
- orascript の移動（サブプロジェクト 4）
- HA の YAML のリファクター（別セッション）
