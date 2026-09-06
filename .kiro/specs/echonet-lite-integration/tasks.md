# HEMS Echonet Lite Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or inline execution to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Home AssistantへHEMS Echonet Lite v0.8.8を再現可能なAnsible構成で導入し、Rinnai MBC-342Vを検出する。

**Architecture:** 既存のcustom integration管理方式に合わせ、`v0.8.8`のimmutable commitをroot管理checkoutへ取得し、`custom_components/echonet_lite`を完全同期する。Home Assistant再起動後にconfig flowをMCP経由で実行し、UDPマルチキャスト探索で機器とentitiesを登録する。

**Tech Stack:** Ansible、Home Assistant Core 2026.8.3 Container、HEMS Echonet Lite v0.8.8、mcporter Home Assistant MCP

## Global Constraints

- リポジトリは`https://github.com/sayurin/hems_echonet_lite.git`を使い、versionは`v0.8.8`のcommit `2f17cf23bbfb2503cdc3cf239376bbfdc51fd02f`へ固定する。
- Home Assistant設定ディレクトリはホスト側`/srv/homeassistant/config`、コンテナ側`/config`とする。
- Home Assistant Containerの既存`network_mode: host`を変更しない。
- 機器IPの固定やDHCP reservationを本変更へ含めない。
- 従来版ECHONETLite Platformを同時導入しない。
- ユーザーから明示依頼がないためGit commitを作成しない。

---

### Task 1: Ansible custom integration管理

**Files:**
- Modify: `roles/homeassistant/vars/main.yml`
- Modify: `roles/homeassistant/tasks/main.yml`

**Interfaces:**
- Consumes: 既存の`custom_components` directoryと`homeassistant: Restart` handler
- Produces: `/srv/homeassistant/config/custom_components/echonet_lite`と`homeassistant_hems_echonet_lite_version`

- [ ] **Step 1: 固定version変数を追加する**

`roles/homeassistant/vars/main.yml`のアルファベット順を保ち、次を追加する。

```yaml
homeassistant_hems_echonet_lite_version: 2f17cf23bbfb2503cdc3cf239376bbfdc51fd02f  # v0.8.8
```

- [ ] **Step 2: cloneタスクを追加する**

`roles/homeassistant/tasks/main.yml`のcustom integration群で、`frosted-glass`と`tuya`の間にroot管理directory作成とcloneタスクを追加する。check modeではAnsible標準の予測だけを行い、checkoutを変更しない。

```yaml
- name: "echonet-lite : Clone HEMS integration"
  ansible.builtin.git:
    repo: https://github.com/sayurin/hems_echonet_lite.git
    dest: /var/lib/ansible/homeassistant/hems-echonet-lite
    version: "{{ homeassistant_hems_echonet_lite_version }}"
    force: true
  register: homeassistant_hems_echonet_lite_git
  tags:
    - homeassistant
    - install
    - custom
    - echonet-lite
    - homeassistant_echonet_lite
    - homeassistant_echonet_lite_install
```

- [ ] **Step 3: checkout清掃タスクを追加する**

tracked変更はcloneタスクの`force: true`で破棄し、untracked/ignoredファイルを次のタスクで除去する。

```yaml
- name: "echonet-lite : Clean HEMS integration checkout"
  ansible.builtin.command:
    argv:
      - git
      - -C
      - /var/lib/ansible/homeassistant/hems-echonet-lite
      - clean
      - -ffdx
  register: homeassistant_hems_echonet_lite_clean
  changed_when: >-
    homeassistant_hems_echonet_lite_clean.stdout | default('') | length > 0
  tags:
    - homeassistant
    - install
    - custom
    - echonet-lite
    - homeassistant_echonet_lite
    - homeassistant_echonet_lite_install
```

- [ ] **Step 4: 完全同期タスクを追加する**

cloneタスク直後に次を追加する。通常実行では削除済みupstreamファイルも除去し、check modeでは同期をskipして延期メッセージを表示する。

```yaml
- name: "echonet-lite : Synchronize HEMS integration"
  ansible.builtin.command:
    cmd: >-
      rsync --archive --delete --itemize-changes --omit-dir-times
      --exclude=__pycache__/
      /var/lib/ansible/homeassistant/hems-echonet-lite/custom_components/echonet_lite/
      /srv/homeassistant/config/custom_components/echonet_lite/
  register: homeassistant_hems_echonet_lite_sync
  changed_when: homeassistant_hems_echonet_lite_sync.stdout | length > 0
  notify: "homeassistant: Restart"
  when: not ansible_check_mode
  tags:
    - homeassistant
    - config
    - custom
    - echonet-lite
    - homeassistant_echonet_lite
    - homeassistant_echonet_lite_config
    - homeassistant_echonet_lite_install
```

- [ ] **Step 5: 差分を確認する**

Run:

```bash
git -P diff -- roles/homeassistant/vars/main.yml roles/homeassistant/tasks/main.yml
```

Expected: immutable SHA変数、配置先directory tag、root管理checkout・clean・同期・check mode報告タスクだけが追加され、無関係な設定が変更されていない。

- [ ] **Step 6: Ansible構文を検証する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml --syntax-check
```

Expected: `playbook: singleton_int1.yml`を表示し、終了コード0になる。

### Task 2: fox.rewse.jpへ適用

**Files:**
- Deploy: `/srv/homeassistant/config/custom_components/echonet_lite` on `fox.rewse.jp`

**Interfaces:**
- Consumes: Task 1の`homeassistant_echonet_lite` tagsと1Password Service Account
- Produces: 再起動後に`echonet_lite`をロード可能なHome Assistant

- [ ] **Step 1: 1Password lookupを実読取で確認する**

Run:

```bash
direnv exec . op read op://ansible/citpxpqr6evzwwndtzjugdoesi/password >/dev/null
```

Expected: 終了コード0になる。

- [ ] **Step 2: check modeを実行する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant_echonet_lite --check
```

Expected: 終了コード0になり、checkoutの変更・清掃・配置先同期を行わず、同期延期メッセージが報告される。

- [ ] **Step 3: 対象tagsを実適用する**

Run:

```bash
direnv exec . ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags homeassistant_echonet_lite
```

Expected: 終了コード0になり、integrationファイルが配置され、通知されたHome Assistant handlerが再起動を行う。

- [ ] **Step 4: Home Assistantの復帰を確認する**

Run:

```bash
mcporter call home-assistant.ha_get_system_health 2>&1 | cat
```

Expected: `success: true`かつversionが`core-2026.8.3`になる。

### Task 3: integration構成とMBC-342V検出

**Files:**
- Configure: Home Assistant config entry domain `echonet_lite`

**Interfaces:**
- Consumes: Task 2でロードされたcustom integrationと`224.0.23.0:3610/UDP`
- Produces: `loaded` config entry、MBC-342V device、状態取得可能なentities

- [ ] **Step 1: config flow schemaを取得する**

Run:

```bash
mcporter call home-assistant.ha_set_integration domain=echonet_lite 2>&1 | cat
```

Expected: integration追加が入力待ちになる場合は`data_schema`にネットワークインターフェースのfield名と選択肢が返る。入力不要で完了した場合はそのconfig entryをStep 3で確認する。

- [ ] **Step 2: Autoインターフェースでconfig flowを完了する**

Step 1で返った`data_schema`のfieldへ`0.0.0.0`を渡す。READMEどおりfield名が`interface`の場合の実行形は次のとおりとする。

```bash
mcporter call home-assistant.ha_set_integration domain=echonet_lite config='{"interface":"0.0.0.0"}' 2>&1 | cat
```

Expected: `success: true`になり、新規config entry IDが返る。

- [ ] **Step 3: config entry状態を確認する**

Run:

```bash
mcporter call home-assistant.ha_get_integration domain=echonet_lite include_options=true 2>&1 | cat
```

Expected: 1件のentryが存在し、stateが`loaded`になる。

- [ ] **Step 4: 検出deviceを確認する**

Run:

```bash
mcporter call home-assistant.ha_get_device integration=echonet_lite 2>&1 | cat
```

Expected: `192.168.0.197`に対応するRinnaiまたは瞬間式給湯器class `0x0272`のdeviceが含まれる。

- [ ] **Step 5: entityの現在状態を確認する**

Step 4のdevice responseからentity IDを抽出し、そのまま`ha_get_state`へ渡す。

```bash
device_json="$(mcporter call home-assistant.ha_get_device integration=echonet_lite 2>/dev/null)"
entity_ids="$(printf '%s' "$device_json" | jq -c '[.. | .entity_id? // empty] | unique')"
test "$entity_ids" != '[]'
mcporter call home-assistant.ha_get_state entity_id="$entity_ids" 2>&1 | cat
```

Expected: `test`が終了コード0になり、1件以上のentityが`unknown`や`unavailable`以外の状態または有効な属性を返す。

- [ ] **Step 6: integrationログを確認する**

Run:

```bash
mcporter call home-assistant.ha_get_logs source=error_log search=echonet_lite hours_back=1 limit=100 2>&1 | cat
mcporter call home-assistant.ha_get_logs source=system search=echonet_lite hours_back=1 limit=100 2>&1 | cat
```

Expected: setup errorまたは反復例外がない。単発warningがある場合はdevice/entityの実動作への影響を評価する。
