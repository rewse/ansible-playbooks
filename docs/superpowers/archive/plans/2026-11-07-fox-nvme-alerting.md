# fox NVMe 通知の絞り込み 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fox の NVMe 通知を、リンク断が異常に多いときとドライブが劣化したときだけにする。

**Architecture:** agent に NVMe の SMART を JSON で返す UserParameter を 1 つ足し、Zabbix 側でそれをマスターアイテムにして、JSONPath の依存アイテムに分ける。リンク断はアクティブの `log.count` アイテムで数え、7 日合計のトリガーで通知する。Zabbix のアイテムとトリガーは API（`mcporter call zabbix.*`）で作り、既存トリガー 17024 は削除する。

**Tech Stack:** Ansible（`roles/zabbix_agent`）、Zabbix 7.4 API、nvme-cli 2.8、Python unittest

**Spec:** `docs/superpowers/specs/2026-11-07-fox-nvme-alerting-design.md`

## Global Constraints

- 対象ホストは fox.rewse.jp（hostid 10194）だけ。hotel には `/dev/nvme0` がない。
- リンク断の正規表現は `nvme.*(controller is down|Unable to change power state)`。
- 通知しきい値は `sum(...,7d)>=5`、重要度 Warning（2）。
- critical_warning、media_errors、available_spare のトリガーは High（4）、percentage_used `>=90` は Warning（2）。temperature はトリガーなし。
- media_errors のトリガーは `recovery_mode` 2（なし）、`manual_close` 1。
- API でアイテムやトリガーを作ったら `zabbix-server` を再起動する（AGENTS.md）。
- agent キーは fox で `zabbix_get -s zabbix.rewse.jp` を使って試す（AGENTS.md）。
- Syslog アイテム 29517 は変更しない。

## Review Focus

- NVMe が PCIe から外れて読めないとき、`nvme.smart_log` は空を返し、依存アイテムは unsupported になる。0 を返して健全に見せてはいけない。Task 1 の Step 1 のテストで stderr を捨てる形を固定し、Step 7 で出力を確認する。
- `log.count` は作成時点の既存行を数えない（`skip`）。数えると今日のリセット 2 件がすぐ合計に入る。Task 3 の Step 5 で確認する。
- 温度は JSON ではケルビン（309 など）。摂氏に直さないとグラフが誤解を招く。Task 2 の Step 5 で確認する。
- media_errors のトリガーは次の取得で自動解決しない。Task 2 の Step 5 で `recovery_mode` を読み返す。
- 17024 を消しても Syslog アイテム 29517 は残る。Task 3 の Step 5 で確認する。

---

### Task 1: SMART を返す UserParameter

**Files:**
- Modify: `roles/zabbix_agent/files/raspberrypi.conf`
- Create: `tests/test_zabbix_agent.py`

**Interfaces:**
- Produces: agent キー `nvme.smart_log`。`nvme smart-log /dev/nvme0 -o json` の JSON（`critical_warning`、`temperature`、`avail_spare`、`spare_thresh`、`percent_used`、`media_errors` など）を返し、読めないときは空を返す。

- [ ] **Step 1: spec と plan をコミットする**

```bash
git add docs/superpowers/specs/2026-11-07-fox-nvme-alerting-design.md docs/superpowers/plans/2026-11-07-fox-nvme-alerting.md
git commit -m "docs: plan limiting fox NVMe alerts to abnormal rates"
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_zabbix_aws.py` と同じ形（`pathlib` と `unittest`）で書く。

```python
FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_agent" / "files"

class RaspberrypiConfTest(unittest.TestCase):
    def test_nvme_smart_log_returns_json_and_nothing_on_failure(self):
        text = (FILES / "raspberrypi.conf").read_text()
        self.assertIn(
            "UserParameter=nvme.smart_log,nvme smart-log /dev/nvme0 -o json 2>/dev/null\n",
            text,
        )
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_agent.py -v`
Expected: FAIL（`AssertionError`、行がない）

- [ ] **Step 4: `raspberrypi.conf` の末尾に UserParameter を追加する**

テストの行を、上にコメントを付けて追加する。コメントでは次の 3 点を説明する。agent は root で動くので sudo は要らない。stderr を捨てるので、デバイスを読めないときは出力が空になり、アイテムが unsupported になる。値の取り出しは Zabbix 側の依存アイテムで行う。

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run --with pytest --with ansible-core pytest tests/test_zabbix_agent.py -v`
Expected: PASS

- [ ] **Step 6: fox に適用する**

Run: `direnv exec . ansible-playbook home-primary.yml --limit fox.rewse.jp --tags zabbix_agent_platform --diff`
Expected: 終了コード 0。`Copy Raspberry Pi config` が changed になり、`Restart zabbix-agent` が走る。

- [ ] **Step 7: キーを試す**

Run: `ssh fox.rewse.jp 'zabbix_get -s zabbix.rewse.jp -k nvme.smart_log' | jq -c '[.critical_warning, .media_errors, .avail_spare, .spare_thresh, .percent_used, .temperature]'`
Expected: 6 つの数値が出る（今は `[0,0,100,5,7,309]` 前後）。

- [ ] **Step 8: 2 回目の実行で changed=0 を確認する**

Run: Step 6 と同じコマンド
Expected: `changed=0`

- [ ] **Step 9: コミットする**

```bash
git add roles/zabbix_agent/files/raspberrypi.conf tests/test_zabbix_agent.py
git commit -m "feat(zabbix_agent): report NVMe SMART log as JSON"
```

### Task 2: SMART のアイテムとトリガー

**Files:** なし（Zabbix API）

**Interfaces:**
- Consumes: Task 1 の `nvme.smart_log`
- Produces: fox のアイテム `nvme.smart_log`（マスター）と、依存アイテム `nvme.smart.avail_spare`、`nvme.smart.critical_warning`、`nvme.smart.media_errors`、`nvme.smart.percent_used`、`nvme.smart.spare_thresh`、`nvme.smart.temperature`

- [ ] **Step 1: まだないことを確認する**

Run: `mcporter call zabbix.item_get 'search={"key_":"nvme.smart"}' 'output=extend' 2>&1 | rg -c 'key_' | cat`
Expected: 出力なし（0 件）

- [ ] **Step 2: マスターアイテムを作る**

`zabbix.item_create`：hostid 10194、interfaceid は fox のエージェントインターフェース（`hostinterface_get` で取得）、type 0（Zabbix agent）、key `nvme.smart_log`、name `NVMe: SMART log`、value_type 4（text）、delay `10m`、history `1d`、trends `0`。

- [ ] **Step 3: 依存アイテムを作る**

各アイテムは type 18（dependent）、`master_itemid` は Step 2 のアイテム、value_type 3、history `90d`、trends `365d`、前処理は JSONPath `$.<field>` 1 つ。

| key | name | JSONPath | 単位・追加前処理 |
|---|---|---|---|
| `nvme.smart.avail_spare` | `NVMe: available spare` | `$.avail_spare` | `%` |
| `nvme.smart.critical_warning` | `NVMe: critical warning` | `$.critical_warning` | なし |
| `nvme.smart.media_errors` | `NVMe: media errors` | `$.media_errors` | なし |
| `nvme.smart.percent_used` | `NVMe: percentage used` | `$.percent_used` | `%` |
| `nvme.smart.spare_thresh` | `NVMe: available spare threshold` | `$.spare_thresh` | `%` |
| `nvme.smart.temperature` | `NVMe: temperature` | `$.temperature` | `°C`、JavaScript `return value - 273;`、value_type 0 |

- [ ] **Step 4: トリガーを作る**

`zabbix.trigger_create`。それぞれ英語の `comments` で、何を検知するかを 1〜2 文で書く。

| description | expression | priority | その他 |
|---|---|---|---|
| `NVMe available spare is at or below threshold on fox` | `last(/fox.rewse.jp/nvme.smart.avail_spare)<=last(/fox.rewse.jp/nvme.smart.spare_thresh)` | 4 | |
| `NVMe critical warning on fox` | `last(/fox.rewse.jp/nvme.smart.critical_warning)<>0` | 4 | |
| `NVMe media errors increased on fox` | `change(/fox.rewse.jp/nvme.smart.media_errors)>0` | 4 | `recovery_mode` 2、`manual_close` 1 |
| `NVMe wear is at or above 90% on fox` | `last(/fox.rewse.jp/nvme.smart.percent_used)>=90` | 2 | |

- [ ] **Step 5: zabbix-server を再起動して値と設定を確認する**

Run: `ssh fox.rewse.jp 'sudo systemctl restart zabbix-server'`。15 分待ってから、`mcporter call zabbix.item_get 'search={"key_":"nvme.smart"}' 'output=extend' 2>&1 | rg -o '\\"(key_|lastvalue|state|error)\\": \\"[^\\]*' | cat` と `mcporter call zabbix.trigger_get 'search={"description":"NVMe"}' 'output=extend' 2>&1 | rg -o '\\"(description|value|recovery_mode|manual_close|error)\\": \\"[^\\]*' | cat` を実行する。
Expected: 7 アイテムすべて state 0 で lastvalue がある。temperature は 30〜50 の範囲。4 トリガーとも value 0、error は空、media_errors だけ recovery_mode 2。

### Task 3: リンク断の回数と頻度トリガー

**Files:** なし（Zabbix API）

**Interfaces:**
- Produces: fox のアイテム `log.count[/var/log/syslog,"nvme.*(controller is down|Unable to change power state)",UTF-8,,skip]` とトリガー `NVMe link resets are unusually frequent on fox`

- [ ] **Step 1: アイテムを作る**

`zabbix.item_create`：hostid 10194、type 7（Zabbix agent active）、key は上記、name `NVMe: link resets`、value_type 3、delay `5m`、history `90d`、trends `365d`。

- [ ] **Step 2: トリガーを作る**

expression `sum(/fox.rewse.jp/log.count[/var/log/syslog,"nvme.*(controller is down|Unable to change power state)",UTF-8,,skip],7d)>=5`、priority 2、recovery_mode 0、manual_close 0。comments には英語で次の 2 点を書く。カーネルが自力で復帰するリセットはたまに起きる程度なら問題ないこと。急増は PCIe のリボンケーブル、HAT、コネクターの悪化を示すこと。

- [ ] **Step 3: 既存トリガー 17024 を削除する**

Run: `mcporter call zabbix.trigger_delete 'ids=["17024"]' 2>&1 | cat`
Expected: `triggerids` に 17024 が返る。

- [ ] **Step 4: zabbix-server を再起動する**

Run: `ssh fox.rewse.jp 'sudo systemctl restart zabbix-server'`
Expected: 終了コード 0

- [ ] **Step 5: 状態を確認する**

10 分待ってから次を実行する。
Run: `mcporter call zabbix.item_get 'search={"key_":"log.count"}' 'output=extend' 2>&1 | rg -o '\\"(key_|lastvalue|state|error)\\": \\"[^\\]*' | cat`、`mcporter call zabbix.trigger_get 'filter={"triggerid":"17024"}' 'output=extend' 2>&1 | cat`、`mcporter call zabbix.item_get 'filter={"itemid":"29517"}' 'output=extend' 2>&1 | rg -o '\\"(state|status)\\": \\"[^\\]*' | cat`
Expected: `log.count` は state 0 で lastvalue が `0`（`skip` で今日の 2 件を数えていない）。17024 は空の結果。29517 は status 0、state 0。

### Task 4: Warning が通知されるかの確認

**Files:** なし

- [ ] **Step 1: 通知アクションの条件を読む**

Run: `mcporter call zabbix.action_get 'filter={"eventsource":"0"}' 'output=extend' 2>&1 | cat`。条件が出ない場合は、`selectFilter` を渡せる呼び出し方を `mcporter list zabbix --schema` で探す。
Expected: `Mail alert - Warning` などのアクションの重要度条件がわかる。Warning（2）以上が通知対象なら完了。通知対象でなければ、変更せずにユーザーに報告する。

### Task 5: 検証とアーカイブ

**Files:**
- Move: `docs/superpowers/specs/2026-11-07-fox-nvme-alerting-design.md` → `docs/superpowers/archive/specs/`
- Move: `docs/superpowers/plans/2026-11-07-fox-nvme-alerting.md` → `docs/superpowers/archive/plans/`

- [ ] **Step 1: lint とテストを実行する**

Run: `uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure` と `uv run --with pytest --with ansible-core pytest tests`
Expected: どちらも終了コード 0。

- [ ] **Step 2: spec と plan をアーカイブしてコミットする**

```bash
git mv docs/superpowers/specs/2026-11-07-fox-nvme-alerting-design.md docs/superpowers/archive/specs/
git mv docs/superpowers/plans/2026-11-07-fox-nvme-alerting.md docs/superpowers/archive/plans/
git commit -m "docs: archive the fox NVMe alerting spec and plan"
```
