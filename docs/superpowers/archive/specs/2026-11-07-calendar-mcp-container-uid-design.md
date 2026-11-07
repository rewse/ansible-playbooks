# calendar-mcp のコンテナを専用のホストアカウントで動かす 設計

## 目的

calendar-mcp のコンテナは、イメージが `useradd -r` で作る mcpuser（uid 999、gid 999）で動いている。ホスト側にはこの番号の登録がなく、fox では uid 999 が dnsmasq、gid 999 が systemd-journal に割り当てられている。そのため、IMAP と iCloud のパスワードを持つ `appsettings.json`（0400）とデータディレクトリは、ホストから見ると dnsmasq の所有になる。いまは dnsmasq ユーザーで動くプロセスも systemd-journal のメンバーもいないが、どちらかが現れた時点で、そのプロセスやユーザーがパスワード、DataProtection の鍵、ログを読める。

コンテナを、ホストに登録した calendar-mcp 専用のアカウントで動かし、この重なりをなくす。

## ゴール

- コンテナのプロセスと、データディレクトリ、`appsettings.json` の所有者が、ホストの `calendar-mcp` アカウントになる
- 同じ番号を別のアカウントが持っているホストでは、ロールが黙って重ねずに失敗する
- 既存のデータ（DataProtection の鍵、ログ、admin claim code）は引き継ぎ、作り直さない
- 2 回目の実行は `changed=0` になる

## 範囲外

- fork の Dockerfile の変更。mcpuser の番号はイメージのまま残し、実行時に上書きする
- userns-remap など Docker 全体の設定
- 古い所有者のファイルが残っていないかを定期的に調べる仕組み

## 方針

次の三つを比べ、A を採る（利用者が A を選んだ）。

- A: uid と gid を `vars/main.yml` に固定し、その番号でホストに `calendar-mcp` のシステムアカウントを作る。compose の `user:` でコンテナの実行ユーザーを上書きする。番号が `/etc/passwd` と `/etc/group` に載るので、あとからパッケージが作るシステムアカウントはその番号を使わない。番号がすでに別のアカウントのものなら、user モジュールが失敗して気づける。filebrowser が実行ユーザーを上書きしているのと同じ形で、AGENTS.md の「UID は `vars/main.yml` に置く」にも合う
- B: zabbix-mcp と同じく、番号を決めずに `system: true` でアカウントを作る。番号を選ばずに済むが、compose の `user:` とファイルの所有者には数値が要るので、config と container の各コンポーネントが実行時に番号を調べる処理を持つことになる。アカウントがまだない初回の `--check` では番号が分からず、その分岐も要る
- C: fork の Dockerfile に mcpuser の uid を変える ARG を足す。upstream に出す理由のない fork 固有の変更が増え、ホストへの登録も別途要るので採らない

## 設計

### 番号

uid、gid ともに 980 とする（実装者の判断）。fox では uid も gid も空いている。Ubuntu はシステムアカウントの番号を 999 から下へ空きを探して割り当て、fox ではいま 985 から 999 までが埋まっている。980 を登録しておけば、以後の割り当てはこの番号を飛ばす。

`vars/main.yml` の `calendar_mcp_uid` を 980 にし、`calendar_mcp_gid: 980` を足す。コメントには、イメージの mcpuser が 999 で、その番号はホストでは別のアカウントに割り当てられうるため、登録した番号で上書きすることを書く。

### アカウント

新しいコンポーネント `tasks/user.yml`（タグ `calendar_mcp_user`）を `tasks/main.yml` の先頭に import する。

- `user | Create system group`: `ansible.builtin.group` で `calendar-mcp` を `gid: "{{ calendar_mcp_gid }}"`、`system: true` で作る
- `user | Create system user`: `ansible.builtin.user` で `calendar-mcp` を `uid: "{{ calendar_mcp_uid }}"`、`group: calendar-mcp`、`system: true`、`shell: /usr/sbin/nologin`、`home: "{{ calendar_mcp_data_dir }}"`、`create_home: false` で作る

ほかのコンポーネントは番号で所有者を指定するので、アカウントの有無に関係なく単独のタグで動く。

### 実行ユーザーと所有者

- `templates/compose.yaml.j2`: 各サービスに `user: "{{ calendar_mcp_uid }}:{{ calendar_mcp_gid }}"` を足す
- `tasks/config.yml` の `config | Deploy settings`: `group` を `calendar_mcp_gid` にする（`owner` は `calendar_mcp_uid` のまま）
- `tasks/container.yml` の `container | Create data directories`: `group` を `calendar_mcp_gid` にする
- `tasks/container.yml` に `container | Own data files` を足す。`container | Create data directories` の直後で、各ユーザーのデータディレクトリに `recurse: true` で `owner` と `group` だけを当てる（`mode` は当てない。ファイルにディレクトリの 0750 が付くため）。コンテナが別の番号で書いたファイルが残っていると、新しい実行ユーザーは 0600 の鍵を読めず、ログにも追記できない。`container | Start containers` は compose の変更を見てその場でコンテナを作り直し、healthy になるまで待つので、所有者の付け替えはそれより前に済ませる必要がある

コンテナの `/app` 以下はすべて他者に読み取りを許しているので、uid 980 でもアプリを読める（`docker run --user 980:980` で確認済み）。HOME は `/` になるが、ルートファイルシステムは読み取り専用で、いまの `/app` にも書けないので変わらない。

### テスト

`tests/test_calendar_mcp.py` に足す。

- compose の各サービスの `user:` と、user コンポーネントが作るアカウントの uid と gid、`appsettings.json` とデータディレクトリの所有者が、すべて同じ番号になる
- `container | Own data files` が再帰的に所有者だけを当て、`container | Start containers` より前にある
- `tasks/main.yml` の import 順の期待値の先頭に `user.yml` を足す

## 検証

- `--tags calendar_mcp` で適用し、両コンテナが healthy になる
- `docker exec calendar-mcp-ts id` が uid 980 を返し、ホストの `ps` で dotnet が `calendar-mcp` として見える
- `/srv/calendar_mcp` 以下と `appsettings.json` の所有者が `calendar-mcp` になる
- 鍵ファイルの数が変わらず（DataProtection が鍵を作り直していない）、リクエスト後に当日のログへ追記される
- `/health/ts` と `/health/ubiqu` が 200 を返す
- 2 回目の適用が `changed=0` になる
