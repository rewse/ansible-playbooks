# TeslaMate fox配備 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or execute the tasks inline in order. Each task has its own RED, GREEN, and verification steps.

**Goal:** foxへTeslaMateとGrafanaをDocker配備し、既存Aurora PostgreSQLとMosquittoへ接続して、2つのHTTPSホスト名で公開する。

**Architecture:** `/etc/compose.yml`へTeslaMateとGrafanaの2サービスを追加する。Webポートはloopbackだけにbindし、ApacheがTLS終端と認証を担当する。秘密値は1Passwordからmode `0600`のenvファイルへ書き、ComposeとApache設定には含めない。

**Tech Stack:** Ansible、YAML、Jinja2、Docker Compose v2、Apache 2、1Password CLI、Amazon Aurora PostgreSQL、Mosquitto

## Global Constraints

- 既存のHome Assistant未コミット変更には触れない。
- コミットは作成しない。
- Aurora DBとロールの初期化、およびDNS変更はroleへ含めない。
- 秘密値をコマンドライン、Ansibleログ、diff、Compose、Apache vhostへ出さない。
- `teslamate.rewse.jp`はApache Basic Auth、`grafana.rewse.jp`はGrafanaログインで保護する。
- TeslaMateは`127.0.0.1:4001`、Grafanaは`127.0.0.1:3000`だけに公開する。
- イメージは既存の`docker/quarantine` roleで安定版semantic version tagを解決し、digest付き参照を使う。

---

### Task 1: テンプレート契約テストをREDにする

**Files:**
- Create: `roles/teslamate/tests/fixtures.yml`
- Create: `roles/teslamate/tests/render_templates.yml`

**Interfaces:**
- Consumes: Ansible組み込みのJinja2レンダラーとYAML parser
- Produces: Compose、env、Apache vhostの出力契約を検証するローカルplaybook

- [x] **Step 1: ダミー変数を作る**

`fixtures.yml`へ、テンプレートが参照する全変数を定義する。秘密値には`DUMMY_DB_PASSWORD`、`DUMMY_ENCRYPTION_KEY`、`DUMMY_GRAFANA_PASSWORD`、`DUMMY_MQTT_PASSWORD`を使い、実際の`op read`は呼ばない。イメージ参照は次のdigest形式にする。

```yaml
teslamate_image_ref: teslamate/teslamate:4.2.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
teslamate_grafana_image_ref: teslamate/grafana:4.2.0@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

- [x] **Step 2: レンダリングテストを書く**

`render_templates.yml`はlocalhostで5テンプレートを`lookup('template', ...)`によりレンダリングする。Compose fragmentには`services:\n`を前置して`from_yaml`へ渡し、次を`ansible.builtin.assert`で確認する。

```yaml
- name: "teslamate-test : Parse compose template"
  ansible.builtin.set_fact:
    teslamate_test_compose: >-
      {{ ('services:\n' ~ lookup('template', '../templates/compose.yml.j2')) | from_yaml }}

- name: "teslamate-test : Verify compose contract"
  ansible.builtin.assert:
    that:
      - teslamate_test_compose.services.teslamate.image == teslamate_image_ref
      - teslamate_test_compose.services['teslamate-grafana'].image == teslamate_grafana_image_ref
      - teslamate_test_compose.services.teslamate.ports == ['127.0.0.1:4001:4000']
      - teslamate_test_compose.services['teslamate-grafana'].ports == ['127.0.0.1:3000:3000']
      - "'DUMMY_DB_PASSWORD' not in lookup('template', '../templates/compose.yml.j2')"
```

envテストはTeslaMate側の`DATABASE_SSL=true`、`DATABASE_SSL_CA_CERT_FILE=/etc/ssl/certs/aws-rds-global-bundle.pem`、MQTT認証、`VIRTUAL_HOST`、`CHECK_ORIGIN=true`を確認する。Grafana側は`DATABASE_SSL_MODE=require`、`GF_AUTH_ANONYMOUS_ENABLED=false`、管理ユーザーを確認する。vhostテストはServerName、wildcard証明書、`X-Forwarded-Proto`、WebSocket proxy、TeslaMate側だけのBasic Authを確認する。

- [x] **Step 3: テストが失敗することを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: `roles/teslamate/templates/compose.yml.j2`が存在しないため`AnsibleError`でFAILする。

---

### Task 2: role変数、秘密env、Composeを実装する

**Files:**
- Create: `roles/teslamate/vars/main.yml`
- Create: `roles/teslamate/templates/compose.yml.j2`
- Create: `roles/teslamate/templates/teslamate.env.j2`
- Create: `roles/teslamate/templates/grafana.env.j2`

**Interfaces:**
- Consumes: `op://ansible/PostgreSQL - TeslaMate/*`、`op://ansible/Mosquitto/credential`、`op://ansible/TeslaMate/*`、`op://ansible/Grafana - TeslaMate/*`
- Produces: `teslamate_image_ref`と`teslamate_grafana_image_ref`を参照するCompose fragment、2つのenvファイル

- [x] **Step 1: role変数を定義する**

`vars/main.yml`へ次を定義する。

```yaml
teslamate_basic_auth_password: "{{ lookup('pipe', 'op read op://ansible/TeslaMate/password') }}"
teslamate_basic_auth_username: "{{ lookup('pipe', 'op read op://ansible/TeslaMate/username') }}"
teslamate_data_dir: /srv/teslamate
teslamate_database_ca_checksum: sha256:e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3
teslamate_database_ca_url: https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
teslamate_database_name: "{{ lookup('pipe', 'op read \"op://ansible/PostgreSQL - TeslaMate/database\"') }}"
teslamate_database_password: "{{ lookup('pipe', 'op read \"op://ansible/PostgreSQL - TeslaMate/password\"') }}"
teslamate_database_port: 5432
teslamate_database_tls_host: rewse-pg.cluster-c8xun5aepybs.ap-northeast-1.rds.amazonaws.com
teslamate_database_username: "{{ lookup('pipe', 'op read \"op://ansible/PostgreSQL - TeslaMate/username\"') }}"
teslamate_encryption_key: "{{ lookup('pipe', 'op read \"op://ansible/TeslaMate/encryption key\"') }}"
teslamate_grafana_admin_password: "{{ lookup('pipe', 'op read \"op://ansible/Grafana - TeslaMate/password\"') }}"
teslamate_grafana_admin_username: "{{ lookup('pipe', 'op read \"op://ansible/Grafana - TeslaMate/username\"') }}"
teslamate_grafana_hostname: grafana.rewse.jp
teslamate_grafana_port: 3000
teslamate_hostname: teslamate.rewse.jp
teslamate_mqtt_host: host.docker.internal
teslamate_mqtt_password: "{{ lookup('pipe', 'op read op://ansible/Mosquitto/credential') }}"
teslamate_mqtt_username: pub_client
teslamate_port: 4001
```

変数はアルファベット順に並べる。

- [x] **Step 2: envテンプレートを実装する**

TeslaMate envには`DATABASE_HOST/PORT/NAME/USER/PASS`、`DATABASE_SSL=true`、`DATABASE_SSL_CA_CERT_FILE`、`MQTT_HOST/PORT/USERNAME/PASSWORD`、`ENCRYPTION_KEY`、`TZ=Asia/Tokyo`、`VIRTUAL_HOST`、`CHECK_ORIGIN=true`を入れる。Grafana envには同じDB接続、`DATABASE_SSL_MODE=require`、`GRAFANA_PASSWD`、`GF_SECURITY_ADMIN_USER/PASSWORD`、`GF_AUTH_BASIC_ENABLED=true`、`GF_AUTH_ANONYMOUS_ENABLED=false`、`GF_SERVER_ROOT_URL`を入れる。

値はdotenvで安全に扱えるよう引用する。少なくとも`#`、`$`、`=`、空白を含むダミー値でローカルテストし、値が欠落しない形式にする。

- [x] **Step 3: Composeテンプレートを実装する**

```yaml
  teslamate:
    container_name: teslamate
    image: {{ teslamate_image_ref }}
    env_file:
      - {{ teslamate_data_dir }}/teslamate.env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "127.0.0.1:{{ teslamate_port }}:4000"
    volumes:
      - {{ teslamate_data_dir }}/import:/opt/app/import
      - /etc/localtime:/etc/localtime:ro
    cap_drop:
      - all
    restart: unless-stopped
```

同じfragmentへ`teslamate-grafana`を追加し、`teslamate_grafana_image_ref`、Grafana env、loopbackの3000番、`/srv/teslamate/grafana:/var/lib/grafana`を使う。Composeには秘密値を書かない。

- [x] **Step 4: GREENを確認する**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: envとComposeに関するassertはPASSする。Apacheテンプレートがまだない場合はその検査でFAILしてよい。

---

### Task 3: Apache proxyと認証を実装する

**Files:**
- Create: `roles/teslamate/templates/teslamate.rewse.jp.conf.j2`
- Create: `roles/teslamate/templates/grafana.rewse.jp.conf.j2`
- Create: `roles/teslamate/handlers/main.yml`

**Interfaces:**
- Consumes: loopbackのTeslaMate 4001番、Grafana 3000番、`/etc/apache2/.teslamate.htpasswd`
- Produces: TLS VirtualHost 2つと、configtest成功時だけApacheをreloadするhandler

- [x] **Step 1: TeslaMate vhostを実装する**

公式Apacheガイドに合わせて`ProxyPass /live/websocket ws://127.0.0.1:4001/live/websocket`を通常の`ProxyPass /`より前へ置く。`<Proxy "http://127.0.0.1:4001/*">`でBasic Authを要求し、公式ガイドどおりLiveView WebSocketを扱う。`SSLEngine on`、`ProxyPreserveHost on`、`RequestHeader set X-Forwarded-Proto "https"`、wildcard証明書を設定する。

- [x] **Step 2: Grafana vhostを実装する**

HTTP proxyに加え、`/api/live/ws`を`ws://127.0.0.1:3000/api/live/ws`へ転送する。Basic Authは付けず、Grafana自身の認証を使う。TLS、Host、`X-Forwarded-Proto`はTeslaMate側と同じにする。

- [x] **Step 3: handlerを実装する**

コンテナhandlerは`community.docker.docker_compose_v2`で対象サービスだけを`recreate: always`にする。Apacheは2段handlerにする。

```yaml
- name: "teslamate: Validate Apache configuration"
  ansible.builtin.command: apache2ctl configtest
  changed_when: true
  notify: "teslamate: Reload Apache"

- name: "teslamate: Reload Apache"
  ansible.builtin.systemd:
    name: apache2
    state: reloaded
```

vhost、module、siteの変更は`teslamate: Validate Apache configuration`をnotifyする。configtestが失敗した場合はreload handlerへ進まない。

- [x] **Step 4: 全テンプレートテストをGREENにする**

Run:

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: 全assertがPASSする。

---

### Task 4: roleタスクとplaybook統合を実装する

**Files:**
- Create: `roles/teslamate/tasks/main.yml`
- Modify: `singleton_int1.yml`

**Interfaces:**
- Consumes: `docker/quarantine`が返す`docker_quarantine_image_ref`、既存Docker、Apache、Mosquitto
- Produces: `/srv/teslamate`、2つのenv、Compose managed block、htpasswd、Apache sites、起動済み2サービス

- [x] **Step 1: 2つのイメージ参照を解決して即時退避する**

TeslaMateとGrafanaを別々に`docker/quarantine`へ渡す。両方のtag patternは`'^\d+\.\d+\.\d+$'`とする。各include直後に次のように退避する。

```yaml
- name: "teslamate : Preserve TeslaMate image reference"
  ansible.builtin.set_fact:
    teslamate_image_ref: "{{ docker_quarantine_image_ref }}"

- name: "teslamate : Preserve Grafana image reference"
  ansible.builtin.set_fact:
    teslamate_grafana_image_ref: "{{ docker_quarantine_image_ref }}"
```

以後の配備タスクは`teslamate_image_ref | length > 0 and teslamate_grafana_image_ref | length > 0`を条件にする。片方だけで配備しない。

- [x] **Step 2: ディレクトリと秘密envを配備する**

`/srv/teslamate`と`import`はroot所有`0755`とする。Grafana data directoryは公式Grafanaイメージの実行ユーザーに合わせてowner `472`、group `0`、mode `0750`とする。AWS公式RDS global CA bundleは`get_url`の`checksum`でSHA-256を検証し、`/srv/teslamate/global-bundle.pem`へmode `0644`で配備する。envテンプレートはroot所有`0600`、`backup: true`、`no_log: true`とし、それぞれ対応するコンテナhandlerをnotifyする。

初回の`--check`では親ディレクトリが実在しないためenv配置をskipし、ローカルテンプレートテストで内容を担保する。初回apply後のcheckでは通常どおりdiffを判定する。

- [x] **Step 3: Compose blockとサービスを配備する**

`blockinfile`と`lookup('template', 'compose.yml.j2')`で`# {mark} ANSIBLE MANAGED BLOCK teslamate`を追加する。`community.docker.docker_compose_v2`は`services: [teslamate, teslamate-grafana]`、`state: present`、`pull: missing`とする。

- [x] **Step 4: htpasswdを秘密漏洩なしで管理する**

`apache2-utils`を導入し、`htpasswd -i`へパスワードをstdinで渡す。検証と更新の両タスクを`no_log: true`にし、パスワードをargvへ入れない。既存hashが有効なら更新しない。ファイルはroot:`www-data`、mode `0640`とする。初回check modeでは作成コマンドを実行しない。

- [x] **Step 5: Apache modulesとsitesを配備する**

`auth_basic`、`headers`、`proxy`、`proxy_http`、`proxy_wstunnel`、`rewrite`、`ssl`を有効化する。2つのvhostを配置し、`a2ensite teslamate.rewse.jp`と`a2ensite grafana.rewse.jp`を冪等に実行する。変更時はApache検証handlerをnotifyする。

- [x] **Step 6: `singleton_int1.yml`へroleを追加する**

`docker`、`httpd`、`mosquitto`がすべて先に実行されるよう、`syslogd`の後、`zabbix/server`の前へ`teslamate`を追加する。Home Assistant関連行は変更しない。

---

### Task 5: 静的検証とfox check modeを実行する

**Files:**
- Verify: `roles/teslamate/**`
- Verify: `singleton_int1.yml`

**Interfaces:**
- Consumes: 完成したroleと1Password項目
- Produces: RED/GREEN、syntax、lint、check modeの実行証拠

- [x] **Step 1: 1Password参照を値を表示せず確認する**

Run:

```bash
direnv exec . op read "op://ansible/PostgreSQL - TeslaMate/password" >/dev/null
direnv exec . op read "op://ansible/TeslaMate/encryption key" >/dev/null
direnv exec . op read "op://ansible/Grafana - TeslaMate/password" >/dev/null
```

Expected: すべてexit 0で標準出力なし。

- [x] **Step 2: テンプレートテスト、syntax、lintを実行する**

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
ansible-playbook singleton_int1.yml --syntax-check
ansible-lint roles/teslamate singleton_int1.yml
```

Expected: すべてexit 0。lintが環境にない場合だけ、その事実を記録してsyntaxとテストを代替証拠にする。

- [x] **Step 3: foxへcheck modeを実行する**

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate \
  --check \
  --diff
```

Expected: exit 0。envとhtpasswdのタスクは`no_log`により秘密値を表示しない。初回checkでは存在しない親ディレクトリへのenv配置とhtpasswd作成をskipしたことが明示される。

- [x] **Step 4: 差分範囲を確認する**

```bash
git -P status --short
git -P diff -- singleton_int1.yml roles/teslamate .kiro/specs/teslamate-fox | cat
```

Expected: TeslaMate spec、role、`singleton_int1.yml`だけが今回の変更であり、既存のHome Assistant変更内容は変わっていない。

---

### Task 6: レビュー後の本番適用と動作確認

**Files:**
- No code changes unless review or validation finds a defect

**Interfaces:**
- Consumes: レビュー済みroleと本番適用の明示確認
- Produces: 稼働中のTeslaMate、Grafana、HTTPS endpoints

- [x] **Step 1: コードレビューとセキュリティレビューを行う**

インフラ、秘密値、外部公開を扱うため、code-reviewerとsecurity-reviewerで独立レビューする。指摘を反映した場合はTask 5を再実行する。

- [x] **Step 2: 本番適用前に変更とリスクを提示して確認を得る**

対象はDocker image pull、コンテナ2つの作成、Apache sitesの有効化、Basic Authファイル作成である。既存Auroraデータを削除する処理は含まない。問題時はsites disableとComposeサービス停止で戻せる。

- [x] **Step 3: 承認後にfoxへ適用する**

```bash
direnv exec . ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate
```

- [x] **Step 4: ホスト内で検証する**

Composeサービス状態、コンテナhealth/log、Aurora migration、MQTT接続、`apache2ctl configtest`を確認する。DNSがNXDOMAINの間はlocalhostへHost headerとBasic Authを付けてproxyを検証する。

- [x] **Step 5: DNS作成後に外部検証する**

`teslamate.rewse.jp`と`grafana.rewse.jp`を`fox.rewse.jp`へのCNAMEとして作成し、DoHで反映を確認する。両URLのTLS、認証、TeslaMate LiveView WebSocket、Grafana datasourceを外部から確認する。
