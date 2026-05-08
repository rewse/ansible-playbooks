# Home Assistant High Availability - タスク一覧

## タスク概要

- [x] Task 1: ドキュメント作成
- [x] Task 2: rsync daemon設定（fox側）
- [x] Task 3: rsync同期設定（hotel側）
- [x] Task 4: hotel側のDocker Compose設定
- [x] Task 5: ヘルスチェックスクリプト作成（hotel側）
- [x] Task 6: systemd timer設定（hotel側）
- [x] Task 7: メール通知設定
- [x] Task 8: Ansible Playbookの統合
- [x] Task 9: 復旧（failback）スクリプト作成

---

## Task 1: ドキュメント作成

**目的:** 設計、タスク、運用手順をドキュメント化

**実装:**
- [x] `.kiro/specs/homeassistant-ha/` ディレクトリを作成
- [x] `requirements.md`: 要件定義
- [x] `design.md`: 設計ドキュメント（アーキテクチャ図、コンポーネント説明）
- [x] `tasks.md`: タスク一覧とチェックリスト
- [x] `operations.md`: 運用手順（手動復旧、設定変更時の注意点、フェイルオーバー確認方法）
- [x] `troubleshooting.md`: トラブルシューティング（よくある問題と解決方法）

**テスト:**
- [x] ドキュメントをレビューし、不足している情報がないか確認

**Demo:**
- [x] ドキュメントが作成され、全体像が把握できる

---

## Task 2: rsync daemon設定（fox側）

**目的:** foxの `/srv/homeassistant/config` をrsync経由で公開

**実装:**
- [x] `roles/homeassistant-ha/primary/tasks/main.yml` を作成
- [x] `roles/homeassistant-ha/primary/templates/rsyncd.conf.j2` を作成（IPv6対応）
- [x] rsync daemonの設定ファイル `/etc/rsyncd.conf` を配置
- [x] systemdで `rsync.service` を起動
- [ ] ファイアウォール設定（家庭LAN内のみの利用のため現状不要）

**テスト:**
- [x] hotelから `rsync rsync://fox.rewse.jp/homeassistant-config/` で接続確認
- [x] 設定ファイル一覧が取得できることを確認

**Demo:**
- [x] rsync経由でfoxの設定ファイル一覧が取得できる

---

## Task 3: rsync同期設定（hotel側）

**目的:** hotelからfoxの設定ファイルを1分ごとに同期

**実装:**
- [x] `/srv/homeassistant/config` ディレクトリを作成
- [x] `roles/homeassistant-ha/secondary/files/homeassistant-sync` を作成
- [x] rsync同期スクリプト `/usr/local/bin/homeassistant-sync` を配置
- [x] `roles/homeassistant-ha/secondary/files/homeassistant-sync.service` を作成
- [x] `roles/homeassistant-ha/secondary/files/homeassistant-sync.timer` を作成
- [x] systemd service/timer を配置（1分ごとに実行）
- [x] 初回同期を実行（約 302MB を同期）

**テスト:**
- [x] タイマーを起動し、1分ごとに同期が実行されることを確認
- [x] `journalctl -u homeassistant-sync.service` でログを確認

**Demo:**
- [x] foxで設定ファイルを変更し、1分後にhotelに反映される

---

## Task 4: hotel側のDocker Compose設定

**目的:** hotelの `/etc/compose.yml` にhomeassistantセクションを追加

**実装:**
- [x] `roles/homeassistant-ha/secondary/tasks/main.yml` でhotel用のcompose設定を追加
- [x] hotelでコンテナをpullするが、起動はしない（`state: present`, `restart: "no"`）
- [x] `/srv/homeassistant/config` ディレクトリを配置（設定ファイルはrsync経由）
- [x] `singleton_int2.yml` を作成（docker ロールと homeassistant-ha/secondary を明示）

**テスト:**
- [x] `docker compose -f /etc/compose.yml config` でエラーがないことを確認
- [x] hotelで手動で `docker compose up homeassistant` を実行し、起動することを確認
- [x] 起動後、`docker compose stop homeassistant` で停止

**Demo:**
- [x] failoverテストでhotelでHome Assistantが起動することを確認

---

## Task 5: ヘルスチェックスクリプト作成（hotel側）

**目的:** foxのHome Assistantの状態を監視し、異常時にフェイルオーバー

**実装:**
- [x] `roles/homeassistant-ha/secondary/templates/homeassistant-failover.j2` を作成
- [x] `/usr/local/bin/homeassistant-failover` を配置
- [x] チェックロジックを実装:
  - [x] foxのAPI（http://fox.rewse.jp:8123/api/）をcurlで確認（HTTP 2xx/3xx/401/403 を健全と判定）
  - [x] 失敗したら30秒待機して再チェック
  - [x] 2回連続失敗したら、SSH経由で `docker ps | grep homeassistant` を実行
  - [x] コンテナが停止していたら、hotelで `docker compose up -d homeassistant` を実行
  - [x] メール通知を送信
- [x] ロックファイル `/var/run/homeassistant-failover.lock` で二重実行を防止

**テスト:**
- [x] スクリプトを手動実行し、正常系の動作を確認（foxが稼働中）
- [x] foxのコンテナを停止し、異常系の動作を確認（約60秒で検知してhotelで起動）
- [x] ロックファイルが正しく動作することを確認

**Demo:**
- [x] foxのコンテナを停止し、スクリプトが自動的にhotelで起動することを確認

---

## Task 6: systemd timer設定（hotel側）

**目的:** ヘルスチェックスクリプトを30秒ごとに実行

**実装:**
- [x] `roles/homeassistant-ha/secondary/files/homeassistant-failover.service` を作成
- [x] `roles/homeassistant-ha/secondary/files/homeassistant-failover.timer` を作成
- [x] systemd service `/etc/systemd/system/homeassistant-failover.service` を配置
- [x] systemd timer `/etc/systemd/system/homeassistant-failover.timer` を配置（30秒ごと）
- [x] タイマーを有効化

**テスト:**
- [x] タイマーを起動: `systemctl start homeassistant-failover.timer`
- [x] タイマーの状態を確認: `systemctl status homeassistant-failover.timer`
- [x] ログで定期実行を確認: `journalctl -u homeassistant-failover.service -f`

**Demo:**
- [x] foxが正常稼働中は何も起こらず、停止すると自動的にフェイルオーバーが発生

---

## Task 7: メール通知設定

**目的:** フェイルオーバー発生時にメール通知

**実装:**
- [x] ヘルスチェックスクリプトにメール送信処理を追加
- [x] 既存のpostfix設定を利用（`roles/postfix/client`、`ubuntu.yml` 経由でhotelにも適用済み）
- [x] 通知内容を実装:
  - [x] 件名: `[ALERT] Home Assistant Failover: fox.rewse.jp -> <hostname>`
  - [x] 本文: フェイルオーバー発生時刻、理由、現在の状態
- [x] 通知先メールアドレスを設定（`group_vars/all/vars` の `email.primary` を参照）

**テスト:**
- [x] failoverテスト時にメール送信を確認
- [x] メールが正しく届くことを確認

**Demo:**
- [x] フェイルオーバー発生時にメールが届く

---

## Task 8: Ansible Playbookの統合

**目的:** 全ての設定をAnsibleで管理

**実装:**
- [x] `roles/homeassistant-ha/primary/` ロールを作成（fox用）
- [x] `roles/homeassistant-ha/secondary/` ロールを作成（hotel用）
- [x] `roles/homeassistant-ha/primary/handlers/main.yml` を作成
- [x] `roles/homeassistant-ha/secondary/handlers/main.yml` を作成
- [x] `roles/homeassistant-ha/secondary/meta/main.yml` で `docker` ロール依存を定義
- [x] `singleton_int1.yml` に `homeassistant-ha/primary` ロールを追加
- [x] `singleton_int2.yml` に `docker` と `homeassistant-ha/secondary` ロールを追加
- [x] `site.yml` に `singleton_int2.yml` を追加
- [x] タグ設定: `homeassistant-ha-primary`, `homeassistant-ha-secondary`, `install`, `config`, `update`

**テスト:**
- [x] `ansible-playbook site.yml --tags homeassistant-ha-primary,homeassistant-ha-secondary --check` でドライラン
- [x] エラーがないことを確認（failed=0）
- [x] `ansible-playbook site.yml --tags homeassistant-ha-primary --limit fox.rewse.jp` でfoxに適用
- [x] `ansible-playbook site.yml --tags homeassistant-ha-secondary --limit hotel.rewse.jp` でhotelに適用

**Demo:**
- [x] Ansibleで全体を適用し、HA構成が完成

---

## Task 9: 復旧（failback）スクリプト作成

**目的:** hotel から fox への切り戻し手順をスクリプト化

**実装:**
- [x] `roles/homeassistant-ha/secondary/templates/homeassistant-failback.j2` を作成
- [x] `/usr/local/bin/homeassistant-failback` を配置
- [x] 対話モード/非対話モード（`--yes --merge STRATEGY`）の両対応
- [x] ロジックを実装:
  - [x] 前提チェック（hotel で HA 起動中 / fox に SSH・rsync 到達可能）
  - [x] フェイルオーバータイマーを停止
  - [x] `rsync --dry-run` で設定差分を表示（SSH 経由、`sudo rsync` 使用）
  - [x] マージ方針選択（push / discard / abort）
  - [x] hotel の HA コンテナを停止
  - [x] `push` 選択時は rsync over SSH で fox に設定を反映（`sudo rsync` 使用）
  - [x] SSH 経由で fox の HA コンテナを起動
  - [x] fox API の応答を最大 120 秒ポーリング（HTTP 2xx/3xx/401/403 を健全と判定）
  - [x] フェイルオーバータイマーを再開
  - [x] 成功/失敗のメール通知
- [x] エラー発生時に自動でフェイルオーバータイマーを再開してから終了
- [x] `operations.md` にスクリプト使用方法を追記

**テスト:**
- [x] スクリプトを `--help` で実行し、使い方が表示されることを確認
- [x] `--yes --merge discard` で failback が実行されることを確認
- [x] `--yes --merge push` で hotel の変更が fox に反映されることを確認（テストマーカーで検証）
- [x] 失敗時にフェイルオーバータイマーが自動復旧することを確認

**Demo:**
- [x] フェイルオーバー状態から `sudo homeassistant-failback --yes --merge discard` で fox に切り戻す
- [x] フェイルオーバー状態から `sudo homeassistant-failback --yes --merge push` で変更を反映して切り戻す

---

## 完了条件

全てのタスクが完了し、以下の状態になっていること：

- [x] foxでrsync daemonが稼働し、設定ファイルが公開されている
- [x] hotelで1分ごとに設定ファイルが同期されている
- [x] hotelでHome Assistantコンテナが準備されている（停止状態）
- [x] hotelで30秒ごとにヘルスチェックが実行されている
- [x] foxのコンテナを停止すると、自動的にhotelで起動する
- [x] フェイルオーバー発生時にメール通知が送信される
- [x] 全ての設定がAnsibleで管理されている
- [x] ドキュメントが整備されている
