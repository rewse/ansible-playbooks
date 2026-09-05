# TeslaMate fox配備設計

## 目的

foxへTeslaMateと付属GrafanaをDockerで配備し、`https://teslamate.rewse.jp/`と`https://grafana.rewse.jp/`で公開する。TeslaMateは既存のAmazon Aurora PostgreSQLとfox上のMosquittoを使用する。

## 構成

```mermaid
graph LR
    CLIENT[外部クライアント] --> APACHE[Apache 2<br/>TLS終端]
    APACHE -->|Basic Auth<br/>127.0.0.1:4001| TESLAMATE[TeslaMate container<br/>port 4000]
    APACHE -->|127.0.0.1:3000| GRAFANA[Grafana container<br/>port 3000]
    TESLAMATE -->|TLS| AURORA[Amazon Aurora PostgreSQL<br/>rewse-pg.rewse.jp:5432]
    GRAFANA -->|TLS required| AURORA
    TESLAMATE -->|MQTT with password| MOSQUITTO[fox Mosquitto<br/>host port 1883]
    ANSIBLE[Ansible role] --> COMPOSE[/etc/compose.yml]
    ANSIBLE --> ENV[/srv/teslamate/*.env]
    ANSIBLE --> APACHE
```

Docker Composeはfoxの既存方式に合わせ、`/etc/compose.yml`へAnsible managed blockを追加する。コンテナは`teslamate`と`teslamate-grafana`の2つとし、PostgreSQLとMosquittoのコンテナは作成しない。

LiteLLMがホストの4000番ポートを使用しているため、TeslaMateは`127.0.0.1:4001`からコンテナの4000番へ転送する。Grafanaは`127.0.0.1:3000`へbindする。いずれもApache以外の外部クライアントから直接到達できない。

## 外部サービス

### Amazon Aurora PostgreSQL

接続情報は次の1Password項目から取得する。

- `op://ansible/f6jqsrpzvfqjxge4ntvalkwbte/database`
- `op://ansible/f6jqsrpzvfqjxge4ntvalkwbte/username`
- `op://ansible/f6jqsrpzvfqjxge4ntvalkwbte/password`

ポートは5432を使用する。TeslaMateの`DATABASE_HOST`には証明書SANと一致するAurora writer endpoint `rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com`を指定する。AWS公式RDS global CA bundleをSHA-256で固定してfoxへ配備し、コンテナへread-only mountしたうえで`DATABASE_SSL=true`と`DATABASE_SSL_CA_CERT_FILE`を設定する。Grafana datasourceは同じwriter endpointへ`DATABASE_SSL_MODE=require`で接続する。

Aurora 16.11には、Ansible管理外の一回限りの初期化として`teslamate` DBとログインロールを作成済みである。ロールは`SUPERUSER`、`CREATEDB`、`CREATEROLE`を持たない。`rds_extension`を付与し、管理可能な拡張を`cube`と`earthdistance`に限定した。TeslaMateのmigrationに必要な`DROP EXTENSION ... CASCADE`は`teslamate` DBでのみ許可した。Aurora delegated extensionが拡張関数を`rdsadmin`所有で作成するため、初回migrationが`ALTER FUNCTION`する`ll_to_earth(double precision, double precision)`と`earth_box(earth, double precision)`だけは所有者を`teslamate`へ移した。

### Mosquitto

TeslaMateはDocker host gateway経由でfox上のMosquitto 2.0.18へ接続する。ユーザー名は`pub_client`、パスワードは`op://ansible/utsespwfv247vhgklpbbpbtboe/credential`を使う。Mosquittoは匿名接続を許可しない。接続はホスト内に閉じるためMQTT TLSは使わない。

## 秘密値

TeslaMateの環境変数は`/srv/teslamate/teslamate.env`、Grafanaの環境変数は`/srv/teslamate/grafana.env`へ分け、所有者をroot、modeを`0600`にする。`/etc/compose.yml`には秘密値を書かない。テンプレート処理は`no_log: true`を指定する。

TeslaMateの暗号化キーとApache Basic Authは次の項目を使う。

- `op://ansible/vt2ez35yutq5ikwrbp46q56oke/encryption key`
- `op://ansible/vt2ez35yutq5ikwrbp46q56oke/username`
- `op://ansible/vt2ez35yutq5ikwrbp46q56oke/password`

Grafana管理者は次の項目を使う。

- `op://ansible/oy677zzpeppxyn3b4xfdfapqvy/username`
- `op://ansible/oy677zzpeppxyn3b4xfdfapqvy/password`

TeslaMateの暗号化キーはTesla APIトークンの復号に必要なため、運用開始後に変更しない。

## Apache

`teslamate.rewse.jp`のVirtualHostは既存の`rewse.jp` wildcard証明書を使い、公式Apacheガイドと同じHTTP Basic Authを要求する。Phoenix LiveViewの`/live/websocket`は公式設定に合わせて処理し、バックエンドへWebSocket proxyする。TeslaMateには`VIRTUAL_HOST=teslamate.rewse.jp`と`CHECK_ORIGIN=true`を設定する。

`grafana.rewse.jp`のVirtualHostはGrafanaへHTTP proxyし、WebSocket upgradeを転送する。Grafanaの匿名アクセスを無効にし、Grafana自身のログインを要求する。両VirtualHostは`X-Forwarded-Proto: https`と元のHostをバックエンドへ渡す。

Apache設定の配置後は`apache2ctl configtest`を実行し、成功した場合だけreloadする。必要な`auth_basic`、`proxy_http`、`proxy_wstunnel`、`rewrite`、`ssl`モジュールをroleで有効化する。

## イメージと更新

TeslaMate本体とGrafanaには公式イメージを使う。既存の`docker/quarantine` roleで安定版のsemantic version tagを解決し、digest付き参照を`/etc/compose.yml`へ書く。コンテナは`restart: unless-stopped`とし、イメージ参照または環境ファイルが変わった場合に対象サービスだけを再作成する。

## role構造

```text
roles/teslamate/
├── handlers/
│   └── main.yml
├── tasks/
│   └── main.yml
├── templates/
│   ├── compose.yml.j2
│   ├── grafana.env.j2
│   ├── grafana.rewse.jp.conf.j2
│   ├── teslamate.env.j2
│   └── teslamate.rewse.jp.conf.j2
└── vars/
    └── main.yml
```

`singleton_int1.yml`へ`teslamate` roleを追加する。DockerとApacheの準備後に実行される位置へ置く。

## DNS

`teslamate.rewse.jp`と`grafana.rewse.jp`は、既存の`hass.rewse.jp`や`nvr.rewse.jp`と同じく`fox.rewse.jp`へのCNAMEとする。現在は両方ともNXDOMAINであり、ローカルとfoxにRoute 53認証情報がないためDNS変更はroleの対象外とする。認証経路を用意した後に本番適用前または適用直後に作成する。

## 検証

実装後に次を確認する。

1. 追加テンプレートを対象にしたローカルテストを先に失敗させ、実装後に成功させる。
2. `ansible-playbook singleton_int1.yml --syntax-check`を実行する。
3. `ansible-lint`が利用可能なら変更ファイルを検査する。
4. `ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags teslamate --check --diff`を実行する。秘密値を含むdiffは出力しない。
5. 本番適用後にComposeサービス、コンテナログ、Aurora migration、Mosquitto接続、Apache configtestを確認する。
6. DNS反映後に両URLのTLS、認証、WebSocket、Grafana datasourceを外部から確認する。

## 失敗時の扱い

Apache configtestに失敗した場合はreloadしない。TeslaMateまたはGrafanaが起動しない場合は既存サービスへ影響させず、対象コンテナのログと環境変数名を確認する。AuroraのDBやロールは一回限りの初期化対象であり、roleの失敗時に削除しない。DNS未設定の間はlocalhostへのHost header付きリクエストでproxyを検証する。
