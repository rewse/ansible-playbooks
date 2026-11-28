# 個人用 Mac の SSH を鍵認証だけにする

## 目的

iPhone と iPad の Rex から、個人用 Mac（youth）の Rex サーバーに SSH で繋げるようにする。繋ぐのは家の LAN か UniFi Teleport の VPN の中からだけなので、外からの経路は作らない。そのかわり、Mac の sshd はパスワードを受け付けず、鍵でしかログインできないようにする。

## ゴール

- `darwin-personal.yml` の実行で、sshd がパスワード認証とキーボード対話式認証（PAM 経由のパスワード）を拒否するようになる。
- iPhone（`rex@atom`）と iPad（`rex@chemical`）の Rex の公開鍵が、Mac の `~/.ssh/authorized_keys` に加わる。今ある RSA の鍵は残す。
- 2 回目の実行は `changed=0` になり、変更がないときに become のパスワードを求めない。

## ゴールにしないこと

- リモートログインをオンにすること。最近の macOS ではコマンドで切り替えるのにフルディスクアクセスが要るので、システム設定 → 一般 → 共有 → リモートログインから手で行う。
- 外から Mac に届く経路（ポート転送、Tailscale）。
- 会社の Mac（`darwin_business`）への適用。
- `authorized_keys` を Ansible で丸ごと管理すること。

## 失敗とみなすこと

- 設定を入れた後も、パスワードやキーボード対話式でログインできる。
- 今ある RSA の鍵が `authorized_keys` から消える。
- 会社の Mac に sshd の設定や鍵が入る。

## 制約

- macOS の `/etc/ssh/sshd_config` は先頭近く（19 行目）で `Include /etc/ssh/sshd_config.d/*` を読み、そこには `100-macos.conf`（`UsePAM yes` など）がある。sshd は同じ項目を最初に読んだ値で決めるので、追加するファイルは `100-` より前に並ぶ名前にする。
- `UsePAM yes` のもとでは、`PasswordAuthentication no` だけだとキーボード対話式でパスワードを聞く道が残る。`KbdInteractiveAuthentication no` も必要になる。
- macOS の sshd は launchd が接続ごとに起動するので、設定を変えても再起動は要らない。
- `/etc/ssh` への書き込みには root が要る。darwin ロールの `path.yml` は、先にチェックサムを比べて、違うときだけ become するようにしている。こうすると、変更がない実行で become のパスワードを聞かれない。同じやり方にそろえる。
- Mac の `~/.ssh/authorized_keys` はどのリポジトリも管理していない。今入っているのは、chezmoi の `id_rsa.pub` と同じ RSA の鍵 1 本だけである。

## 方式の比較

- A. darwin ロールに `sshd` コンポーネントを足し、sshd の設定ファイルと、インベントリにある鍵の追加を扱う。設定と鍵が 1 か所にまとまる。これを選んだ。
- B. 鍵は chezmoi のソースで `authorized_keys` ごと管理し、sshd の設定だけ Ansible で扱う。設定が 2 つのリポジトリに分かれる。
- C. 全部手で行う。Mac を入れ替えたときに再現できない。

## 決まっている設計

- darwin ロールに `tasks/sshd.yml` を足し、`tasks/main.yml` からタグ `darwin_sshd` で import する。版を解決する処理はないので、`update` タグは付けない。
- インベントリ変数は `darwin_sshd_authorized_keys`（公開鍵 1 行ずつのリスト）とする。`inventory/group_vars/darwin_personal/darwin.yml` に iPhone と iPad の鍵を置く。この変数がないホストでは、コンポーネントのタスクを全部飛ばす。
- sshd の設定は `/etc/ssh/sshd_config.d/000-key-only.conf` に置く。中身は `PasswordAuthentication no` と `KbdInteractiveAuthentication no` の 2 行と、それを説明するコメントにする。
- 鍵は `ansible.posix.authorized_key` で、今あるものを消さずに 1 本ずつ足す（`exclusive` は使わない）。

## 実装者に任せること

- 設定ファイルを `files/` に置いて `path.yml` と同じチェックサム比較にするか、別のやり方で「変更がないときは become しない」を満たすか。
- `sshd -t` による検証を入れるかどうか。
- テストの範囲。最低でも、ファイル名が `100-macos.conf` より前に並ぶこと、2 つの項目が `no` であること、鍵の追加が `exclusive` でないこと、変数がないホストで飛ぶことを固定する。
- 適用後の確認方法（`sudo sshd -T` で実際の値を見る、パスワード認証だけを指定した `ssh` が拒否されることを見るなど）。
