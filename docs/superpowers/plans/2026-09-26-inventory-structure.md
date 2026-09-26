# inventory と playbook 構造の刷新 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ホストの type ごとに playbook を 1 本にし、inventory を `inventory/` ディレクトリに構造化する。どのホストの設定内容も変えない。

**Architecture:** 先に main の状態で inventory の出力と check mode の結果を基準として保存する。ブランチ上で inventory、変数、テンプレート、playbook、ドキュメントを変え、inventory の出力を改名の対応表で読み替えて基準と突き合わせ、check mode で変更を報告するタスクの集まりが基準と同じであることを確かめてから、main へ一度に fast-forward する。

**Tech Stack:** ansible-core 2.21.3、ansible-lint 26.8.0、jq、pre-commit（`uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2`）

**Spec:** `docs/superpowers/specs/2026-09-26-inventory-structure-design.md`

## Global Constraints

- 作業はブランチ `refactor/inventory-structure` で行い、検証がすべて通ってから main へ fast-forward して push する（spec の「1 回で切り替える」は、main が途中の状態を経ないことを指す）
- 値の中身は変えない。変えるのは置き場所と名前だけ
- 本番への `--check` なしの実行はしない
- playbook の成否はプロセスの終了コードで判断する。1Password の lookup が失敗したら AGENTS.md の 1Password の節に従う
- playbook の実行は `direnv exec .` 経由で行う
- 基準と比較結果は plan のワークスペース（`.superpowers/sdd/2026-09-26-inventory-structure/`）に置き、コミットしない
- 改名の対応: `ssh_port`→`ansible_port`、`local.ip`→`raspberrypi_primary_address`、`local.ip_2`→`raspberrypi_secondary_address`、`location`→`mhz19_location`、`secondary_diskname`→`ec2_secondary_disk`、`local.fqdn` と `zabbix.server` は削除
- ロール名タグ: `ubuntu`、`raspberrypi`、`ec2`、`chezmoi`、`mhz19`、`postfix_client`、`zabbix_agent`（`zabbix/agent/*` すべて）、`zabbix_server`、`zabbix_mcp`、`zabbix_money_market`、`zabbix_aws`、`homeassistant_ha_primary`、`homeassistant_ha_secondary`、`database_client`、`database_client_gui`。フラットなロールはロール名そのもの

## Review Focus

- `ansible_port` を明示すると、`~/.ssh/config` の `Port` より inventory の値が優先される。値は同じなので接続先は変わらない。Task 5 の check で 3 台とも接続できることで確かめる
- mhz19 のテンプレートは `[% %]` の独自区切りを使う。変数名だけを置き換え、区切りは変えない。Task 5 の check で `mhz192mqtt` に差分が出ないことで確かめる
- ロールの順の入れ替え（`raspberrypi` が `chezmoi`、`postfix/client` より先になる）で、check の変更タスクが増減しないこと。Task 5 の比較で確かめる
- playbook 側のロール名タグが、既存タスクのタグと衝突して `--tags` の選択範囲を広げないこと。Task 3 の `--list-tasks --tags postfix_client` が postfix のタスクだけを返すことで確かめる
- `site.yml` の対象ホストが変わらないこと。Task 3 の `--list-hosts` で alfa、fox、hotel の 3 台だけになることで確かめる

---

### Task 1: 基準を取る

**Files:** なし（ワークスペースに保存）

**Interfaces:**
- Produces: `$W/baseline/inventory/<host>.json`（6 台分）、`$W/baseline/check/<host>.txt`（3 台分）、`$W/changed.sh`（check の出力から `TASK名<TAB>changed` の行を抜き出してソートするスクリプト）

- [ ] **Step 1: ワークスペースを用意する**

`W=$(~/.kiro/skills/subagent-driven-development/scripts/sdd-workspace docs/superpowers/plans/2026-09-26-inventory-structure.md)` とし、`$W/baseline/inventory`、`$W/baseline/check` を作る。main にいること、作業ツリーがきれいなことを `git status --short` で確かめる。

- [ ] **Step 2: inventory の出力を保存する**

`ansible-inventory --list | jq -r '._meta.hostvars | keys[]'` で 6 台を得て、それぞれ `ansible-inventory --host <host> | jq -S . > $W/baseline/inventory/<host>.json`。
Expected: 6 ファイルができ、`fox.rewse.jp.json` に `ssh_port`、`local`、`location` がある

- [ ] **Step 3: check の抽出スクリプトを作る**

`$W/changed.sh` は、ansible-playbook の出力を標準入力で受け、`TASK [...]` 行の名前と、その直後の `changed:` の組を `名前<TAB>changed` で出力し、ソートする。`RUNNING HANDLER [...]` も同じ扱いにする。

- [ ] **Step 4: 3 台の check を保存する**

| ホスト | 流す playbook（順に） |
|---|---|
| fox.rewse.jp | `ubuntu.yml`、`raspberrypi.yml`、`singleton_int1.yml` |
| hotel.rewse.jp | `ubuntu.yml`、`raspberrypi.yml`、`singleton_int2.yml` |
| alfa.rewse.jp | `ubuntu.yml`、`ec2.yml`、`singleton_ext1.yml` |

各 playbook を `direnv exec . ansible-playbook <pb> --limit <host> --check --diff` で流し、出力を連結して `$W/baseline/check/<host>.txt` に保存する。各実行の終了コードを記録する。
Expected: すべて終了コード 0。0 でない場合は原因を ledger に書き、同じ失敗が切り替え後にも出るかどうかを比較の対象にする

- [ ] **Step 5: ledger に記録する**

`$W/progress.md` に基準の取得日時、各 check の終了コード、`changed.sh` で抜き出した行数を書く。

### Task 2: inventory と変数

**Files:**
- Modify: `ansible.cfg`（`inventory = inventory`）
- Create: `inventory/hosts`、`inventory/group_vars/all/site.yml`、`inventory/host_vars/{alfa,fox,hotel}.rewse.jp/*.yml`
- Delete: `hosts`、`group_vars/`
- Modify: `roles/ubuntu/templates/sshd.conf.j2`、`roles/raspberrypi/templates/override.conf.j2`、`roles/raspberrypi/templates/99-config.yaml.j2`、`roles/mhz19/templates/mhz192mqtt.j2`、`roles/ec2/tasks/main.yml`

**Interfaces:**
- Consumes: Task 1 の `$W/baseline/inventory/*.json`
- Produces: グループ `home_primary`、`home_secondary`、`cloud_workstation`（Task 3 の `hosts:` が使う）

- [ ] **Step 1: ブランチを作る**

Run: `git switch -c refactor/inventory-structure`

- [ ] **Step 2: `inventory/hosts` を書く**

ini 形式で、グループはアルファベット順に `cloud_workstation`（alfa）、`darwin_business`、`darwin_personal`、`ec2`（alfa）、`home_primary`（fox）、`home_secondary`（hotel）、`raspberrypi`（fox、hotel）、`ubuntu`（alfa、fox、hotel）、`udm`（sierra）。変数は書かない。

- [ ] **Step 3: 変数ファイルを書く**

`group_vars/all/vars` の中身を `inventory/group_vars/all/site.yml` に移す（中身はそのまま）。host_vars は spec の対応表どおりに作り、値は旧 `group_vars/singleton_*/vars` からそのまま写す。

| ファイル | キー |
|---|---|
| `alfa.rewse.jp/ansible.yml` | `ansible_port` |
| `alfa.rewse.jp/ec2.yml` | `ec2_secondary_disk` |
| `{fox,hotel}.rewse.jp/ansible.yml` | `ansible_port` |
| `{fox,hotel}.rewse.jp/mhz19.yml` | `mhz19_location` |
| `{fox,hotel}.rewse.jp/raspberrypi.yml` | `raspberrypi_primary_address`、`raspberrypi_secondary_address` |

旧 `hosts` と `group_vars/` を `git rm -r` で消し、`ansible.cfg` を直す。

- [ ] **Step 4: 参照を直す**

5 ファイルの参照を新しい名前に置き換える（`ssh_port`→`ansible_port`、`local.ip_2`→`raspberrypi_secondary_address`、`local.ip`→`raspberrypi_primary_address`、`location`→`mhz19_location`、`secondary_diskname`→`ec2_secondary_disk`）。mhz19 の `[% %]` 区切りは変えない。
Run: `rg -n '\bssh_port\b|\blocal\.(ip|fqdn)|\[% location %\]|secondary_diskname|zabbix\.server' roles`
Expected: 出力なし

- [ ] **Step 5: inventory の出力を基準と突き合わせる**

各ホストで、基準を次の jq で読み替えたものと、新しい `ansible-inventory --host <host> | jq -S .` を `diff` する。

```jq
(if has("ssh_port") then .ansible_port = .ssh_port else . end)
| (if has("local") then .raspberrypi_primary_address = .local.ip
     | .raspberrypi_secondary_address = .local.ip_2 else . end)
| (if has("location") then .mhz19_location = .location else . end)
| (if has("secondary_diskname") then .ec2_secondary_disk = .secondary_diskname else . end)
| del(.ssh_port, .local, .location, .secondary_diskname, .zabbix)
```

Expected: 6 台すべて差分なし

- [ ] **Step 6: コミット**

```bash
git add -A ansible.cfg inventory hosts group_vars roles/ubuntu/templates/sshd.conf.j2 roles/raspberrypi/templates roles/mhz19/templates/mhz192mqtt.j2 roles/ec2/tasks/main.yml
git commit -m "refactor: move inventory into a structured directory"
```

### Task 3: playbook

**Files:**
- Create: `home-primary.yml`、`home-secondary.yml`、`cloud-workstation.yml`
- Modify: `site.yml`、`.ansible-lint-ignore`
- Delete: `ubuntu.yml`、`ec2.yml`、`raspberrypi.yml`、`singleton_ext1.yml`、`singleton_int1.yml`、`singleton_int2.yml`

**Interfaces:**
- Consumes: Task 2 のグループ名

- [ ] **Step 1: 3 本の playbook を書く**

1 ファイル 1 play。`name` は `Configure home primary` / `Configure home secondary` / `Configure cloud workstation`、`hosts` は対応するグループ、`become: true`、`remote_user: ubuntu`。ロールは spec の表の順に `- role: <path>` と `tags:`（Global Constraints の名前を 1 つ、インデントした YAML リスト）で並べる。サービスの層は旧 `singleton_*.yml` の順をそのまま使い、home の 2 本はその先頭に `mhz19` を置く。

- [ ] **Step 2: `site.yml` と旧 playbook**

`site.yml` は `name: Import home primary` などの名前付きで 3 本を `ansible.builtin.import_playbook` する（順は cloud-workstation、home-primary、home-secondary）。旧 6 本を `git rm` する。

- [ ] **Step 3: ignore を付け替える**

`.ansible-lint-ignore` から旧 6 本と `site.yml` の行を消し、新しい 3 本それぞれに `role-name[path]` の行を足す（アルファベット順を保つ）。

- [ ] **Step 4: 構文とタグを確かめる**

Run: `for p in *.yml; do ansible-playbook --syntax-check "$p" || echo "FAIL $p"; done`
Expected: `FAIL` なし（`requirements.yml` と `.pre-commit-config.yaml` は playbook ではないので対象から除く）
Run: `ansible-playbook site.yml --list-hosts`
Expected: alfa.rewse.jp、fox.rewse.jp、hotel.rewse.jp の 3 台だけ
Run: `ansible-playbook home-primary.yml --list-tasks --tags postfix_client | rg ' : '`
Expected: `postfix/client` のロールのタスクだけ
Run: `ansible-lint --nocolor; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 5: コミット**

```bash
git add -A site.yml home-primary.yml home-secondary.yml cloud-workstation.yml ubuntu.yml ec2.yml raspberrypi.yml singleton_ext1.yml singleton_int1.yml singleton_int2.yml .ansible-lint-ignore
git commit -m "refactor: write one playbook per host type"
```

### Task 4: ドキュメント

**Files:**
- Modify: `AGENTS.md`（Role Design、Variables）
- Modify: `README.md`（Project Structure、Usage の実行例、Inventory、Variable Management）

- [ ] **Step 1: AGENTS.md を直す**

Role Design の 1 行目の後に、type ごとの playbook の名前（役割名をハイフン）とグループ名（同じ名前をアンダースコア）のルールを足す。Variables の表の inventory の行を `inventory/group_vars/<group>/<role>.yml` と `inventory/host_vars/<host>/<role>.yml` にし、`group_vars/all/` の行を `inventory/group_vars/all/site.yml` にする。表の後に「`ansible.yml` holds connection variables such as `ansible_port` only」を足す。

- [ ] **Step 2: README.md を直す**

Project Structure の図を新しい構成にする。実行例の `ubuntu.yml`、`ec2.yml`、`raspberrypi.yml`、`singleton_int1.yml` を `home-primary.yml` などに置き換える。Inventory のグループ一覧を `inventory/hosts` のグループに合わせる（`internal` は実在しないので消す）。Variable Management のパスを `inventory/` 配下にする。

- [ ] **Step 3: 残りがないことを確かめる**

Run: `rg -n 'singleton|group_vars/(singleton|all/vars)|\bubuntu\.yml|\bec2\.yml|\braspberrypi\.yml' --glob '!docs/**' .`
Expected: 出力なし
Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 4: コミット**

```bash
git add AGENTS.md README.md
git commit -m "docs: describe the inventory and host type playbooks"
```

### Task 5: check の突き合わせと反映

**Files:** なし

**Interfaces:**
- Consumes: Task 1 の `$W/baseline/check/<host>.txt` と `$W/changed.sh`

- [ ] **Step 1: 3 台の check を流す**

`home-primary.yml`（fox）、`home-secondary.yml`（hotel）、`cloud-workstation.yml`（alfa）を `direnv exec . ansible-playbook <pb> --check --diff` で流し、`$W/after/check/<host>.txt` に保存する。
Expected: 3 本とも終了コードが Task 1 と同じ（通常は 0）

- [ ] **Step 2: 変更タスクの集まりを比べる**

各ホストで `diff <($W/changed.sh < $W/baseline/check/<host>.txt) <($W/changed.sh < $W/after/check/<host>.txt)`。
Expected: 差分なし。差分がある場合は、その行が apt の upgrade や cooldown による新しいリリースのように実行時点で変わるものかを、基準との時間差と diff の中身で判断し、ledger に `Ruling:` として残す。そうでない差分は修正してから Step 1 に戻る

- [ ] **Step 3: main に反映する**

Run: `git switch main && git merge --ff-only refactor/inventory-structure && git push origin main && git branch -d refactor/inventory-structure`

- [ ] **Step 4: CI を確かめる**

Run: `gh run list --commit $(git rev-parse HEAD) --json name,conclusion | cat`（完了まで待つ）
Expected: `Ansible Lint`、`Gitleaks` が `success`

- [ ] **Step 5: 完了条件を照合する**

spec の完了条件 4 項目を、Task 2 Step 5、Task 5 Step 2、Task 3 Step 4 と Task 5 Step 4、Task 4 Step 3 の結果で示す。
