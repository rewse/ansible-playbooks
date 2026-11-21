# Docker の未使用イメージ掃除

## 目的

サービスのロールは `aged_release` で解決した新しい `tag@digest` を pull するが、古いイメージを消す処理がない。このため更新のたびにイメージが積み上がる。hotel では Home Assistant のイメージ 9 個（各 3.4GB 前後、使用中は 1 個）が `/`（58G）を 81% まで埋め、Zabbix の「Lack of disk size for /」が鳴った。fox も 109 個中 10 個しか使っておらず、build cache が 3.3GB ある。playbook の実行で未使用のイメージと build cache を消し、再発を防ぐ。

## ゴールと非ゴール

- ゴール: `roles/docker` を使う全ホスト（fox、hotel）で、playbook の実行ごとに、どのコンテナからも参照されないイメージと build cache を消す。
- 非ゴール: 置き換わった直前の世代を次の更新まで残すこと。直前の世代は次の playbook 実行で消える。ロールバックは古い digest を指定して pull し直す。
- 非ゴール: コンテナ、ネットワーク、ボリュームの掃除。停止中のコンテナ（hotel の standby の `homeassistant` など）やデータを消す恐れがあるため対象外とする。
- 非ゴール: playbook を実行しないときの定期的な掃除。

## 案

- A. `roles/docker` に `prune` コンポーネントを足し、`community.docker.docker_prune` を 1 回呼ぶ（採用）。タスク 1 つで済む。直前の世代は次の実行までしか残らない。
- A'. A と同じ場所で、リポジトリごとに使用中より古い世代を 1 つ残して残りを消す。次の更新まで直前の世代を残せるが、イメージの列挙と比較を自前で書くことになり、`docker_prune` 1 回では済まない。
- B. systemd タイマーで週 1 回 `docker image prune -a --filter until=...` を実行する。playbook の外で入ったイメージも消せるが、`until` はイメージの作成日時で判定するため、公開から数日で入る HA のイメージでは直前の世代がすぐ消える。unit ファイルが 2 つ増える。

利用者は A を選び、直前の世代が次の実行で消えることを受け入れた。ロールバックはまれで、pull し直しても数分で済むため。

## 設計

- `roles/docker/tasks/prune.yml` に `prune | Remove unused images and build cache` を置く。`community.docker.docker_prune` に `images: true`、`images_filters: {dangling: false}`、`builder_cache: true`、`builder_cache_all: true` を渡す。
- `roles/docker/tasks/main.yml` の最後で `prune.yml` を `docker_prune` と `update` のタグ付きで import する。`update` を付けるのは、`--tags update` で新しいイメージを入れる実行でも古い世代を片付けるため。
- 全コンテナサービスは `meta/main.yml` で docker に依存するので、prune はサービスのロールより先に動く。停止中でもコンテナがあるイメージ（hotel の standby など）は消えない。
- 冪等性: 消す物がないときは `changed` にならない。イメージを更新した実行の次の実行は、置き換わった世代を消すので `changed` になり、その次で `changed=0` になる。
- check mode では何も消さない。
- fox で最初に消えるのは、open-webui、watchtower、`home-assistant:stable`、`etc-matter-server` などの使われていないイメージと、削除済みの calendar-mcp や旧 matter のビルドに由来する build cache で、残す必要のある物はない。リポジトリに `docker build` や `docker run` はない。

## 実装者に任せること

- check mode での `docker_prune` の挙動確認と、必要なら `check_mode` の扱い。
- ロールのテスト（`tests/`）を足すかどうか。
