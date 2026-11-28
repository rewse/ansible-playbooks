# fox への Rex の導入

## 目的

Superlogical の Rex を fox に入れ、管理ユーザー tats の Rex サーバー（personal server）を常時動かす。Mac のスリープや蓋の開閉と関係なく、長いビルドやエージェントの作業を fox 上のセッションで続けられるようにし、そのセッションに Mac の Rex と iPhone の Rex の両方から SSH で接続する。

## ゴール

- `home-primary.yml` の実行で、fox に Rex が apt パッケージとして入る。
- tats の Rex サーバーが起動時に立ち上がり、ログアウト後も動き続ける。
- Mac と iPhone の Rex から `ssh://tats@fox.rewse.jp:11022` で接続できる。
- iPhone の Rex が作った SSH 公開鍵をインベントリで管理し、tats の `authorized_keys` に載せる。
- Rex の更新は ubuntu ロールの `upgrade.yml`（apt の全体アップグレード）で入る。
- 2 回目の実行は `changed=0` になる。

## ゴールにしないこと

- hotel や alfa への導入。今回は fox だけを対象にする。
- Rex 組み込みの Tailscale、Tailscale Serve、平文 HTTP のリスナー。接続は SSH だけにする。
- 共有サーバー（`rex.service`）とログインサーバー（`rex-login-server.service`）。パッケージに含まれるが、無効のまま残す。
- Rex の Lua 設定（`~/.config/rex/init.lua`）の管理。
- IPv6 で外から fox の SSH に届かない問題の解決。

## 失敗とみなすこと

- Ubuntu の同名パッケージ `rex`（Perl の自動化フレームワーク (R)?ex）が入る、または unattended-upgrades で Rex がそれに置き換わる。
- 既存の鍵が tats の `authorized_keys` から消える、または ubuntu ユーザーの鍵の管理方法が変わる。
- SSH の待ち受けポートやファイアウォールの公開範囲が広がる。

## 制約

- Rex の Linux 版はテスト中で、apt の `stable` チャンネルには `InRelease` がまだない（404）。現時点で使えるのは `preview` だけで、公式の `install.sh` も `stable` がなければ `preview` に切り替える。
- 公式の `install.sh` は、apt の場合に次の 3 つを書く。Ansible でも同じ内容にする。
  - 鍵: `https://pkgs.superlogical.com/rex/keys/rex-archive-keyring.gpg` を `/etc/apt/keyrings/rex-archive-keyring.gpg` に置く。
  - リポジトリ: `/etc/apt/sources.list.d/rex.sources`。`URIs: https://pkgs.superlogical.com/rex/apt`、`Suites: <channel>`、`Components: main`、`Architectures: <dpkg のアーキテクチャ>`、`Signed-By` に上の鍵。
  - pin: `/etc/apt/preferences.d/rex`。`Package: rex` / `Pin: origin pkgs.superlogical.com` / `Pin-Priority: 1001` と、`Package: rex` / `Pin: release *` / `Pin-Priority: -1` の 2 レコードをこの順で書く。2 つ目がないと、unattended-upgrades の実行中やリポジトリが無効になったときに (R)?ex が入る。
- personal server は tats として `rex server install` で systemd のユーザーサービスにし、起動時に立ち上げてログアウト後も動かす。ドキュメントでは sudo は不要とされている。
- `roles/ubuntu/tasks/user.yml` は毎回 `/home/ubuntu/.ssh/authorized_keys` を tats の `authorized_keys` に上書きコピーする。tats の鍵を別のロールから足すと、毎回 `changed` になる。
- fox の SSH は WAN の 11022 番を IPv4 で転送している。IPv6 では外から届かない。iPhone が携帯回線で IPv6 を優先すると繋がらない可能性があるので、繋がらない場合は IPv4 のアドレスを使う。この注意は運用側で扱う。

## 方式の比較

iPhone の鍵の登録先を 3 案で比べ、A を選んだ。

- A. ubuntu ロールが、ubuntu ユーザーの鍵とインベントリで指定した追加の鍵をつないで tats の `authorized_keys` に書く。鍵が Git に残り、冪等性も保てる。Rex と関係のない ubuntu ロールに手を入れる必要がある。
- B. 手で `/home/ubuntu/.ssh/authorized_keys` に足す。Ansible の変更は不要だが、鍵がリポジトリに残らず、ubuntu ユーザーとしても iPhone からログインできるようになる。
- C. rex ロールが `authorized_key` で tats に鍵を足す。ubuntu ロールの上書きコピーとぶつかり、毎回 `changed` になる。

接続方法は SSH、組み込みの Tailscale、Tailscale Serve を比べ、SSH を選んだ。SSH なら tailnet にもファイアウォールにも新しい公開先を作らず、既存の鍵認証と fail2ban の sshd jail をそのまま使える。組み込みの Tailscale を選ぶと、初回のサインインのために auth key を 1Password に置くなどの仕組みが要る。

## 決まっている設計

- 新しいロール `rex` を作り、`home-primary.yml` のサービスの階層にアルファベット順で加える。
- `rex` ロールのコンポーネントは次の 2 つにする。
  - `apt`: 鍵、`rex.sources`、pin を置き、`rex` パッケージを入れる。チャンネルは `preview` にする。`stable` が出るまで使えるチャンネルが `preview` しかないため、その理由をコメントに書き、変数で固定する。
  - `server`: tats の linger を有効にし、tats として `rex server install` を実行して、ユーザーサービスを有効にする。
- ubuntu ロールに、tats に追加する公開鍵のリスト（例: `ubuntu_admin_extra_authorized_keys`、既定は空）を加える。`user | Copy authorized_keys for admin` は、ubuntu ユーザーの鍵の後ろにこのリストをつないだ内容を書く形に変える。リストが空なら、書かれる内容は今と同じにする。
- iPhone の Rex の公開鍵は `inventory/host_vars/fox.rewse.jp/ubuntu.yml` に置く。

## 実装者に任せること

- `deb822_repository` の `signed_by` に URL を渡すか、`get_url` で鍵を置いてから参照するか。鍵の置き場所は `install.sh` と同じ `/etc/apt/keyrings/rex-archive-keyring.gpg` にそろえる。
- `Architectures` に入れる値の求め方（`ansible_facts['architecture']` から dpkg の名前へ変換するなど）。
- `rex server install` が既にインストール済みのときにどう振る舞うかを確かめ、`changed_when` と、実行を飛ばす条件（`creates:` など）を決める。ユーザーサービスの unit ファイルの場所も確かめる。
- linger を有効にする方法（`loginctl enable-linger` を `creates: /var/lib/systemd/linger/tats` 付きで実行するなど）。
- ubuntu ロールで、ubuntu ユーザーの鍵を読んで追加の鍵とつなぐ方法（`slurp` と `copy` の `content` など）。末尾の改行の扱いをそろえ、空リストのときに今の内容と 1 バイトも変わらないようにする。
- テスト（`tests/`）の追加範囲。pin の 2 レコードとその順序、`authorized_keys` の連結は、テストで固定する。
