# Home Assistant High Availability - タスク一覧

## タスク概要

- [ ] Task 1: ドキュメント作成
- [ ] Task 2: rsync daemon設定（fox側）
- [ ] Task 3: rsync同期設定（hotel側）
- [ ] Task 4: hotel側のDocker Compose設定
- [ ] Task 5: ヘルスチェックスクリプト作成（hotel側）
- [ ] Task 6: systemd timer設定（hotel側）
- [ ] Task 7: メール通知設定
- [ ] Task 8: Ansible Playbookの統合

---

## Task 1: ドキュメント作成

**目的:** 設計、タスク、運用手順をドキュメント化

**実装:**
- [x] `.kiro/specs/homeassistant-ha/` ディレクトリを作成
- [x] `requirements.md`: 要件定義
- [x] `design.md`: 設計ドキュメント（アーキテクチャ図、コンポーネント説明）
- [x] `tasks.md`: タスク一覧とチェックリスト
- [ ] `operations.md`: 運用手順（手動復旧、設定変更時の注意点、フェイルオーバー確認方法）
- [ ] `troubleshooting.md`: トラブルシューティング（よくある問題と解決方法）

**テスト:**
- [ ] ドキュメントをレビューし、不足している情報がないか確認

**Demo:**
- [ ] ドキュメントが作成され、全体像が把握できる

---

## Task 2: rsync daemon設定（fox側）

**目的:** foxの `/srv/homeassistant/config` をrsync経由で公開

**実装:**
- [ ] `roles/homeassistant-ha/tasks/main.yml` を作成
- [ ] `roles/homeassistant-ha/files/rsyncd.conf` を作成
- [ ] rsync daemonの設定ファイル `/etc/rsyncd.conf` を配置
- [ ] systemdで `rsync.service` を起動
- [ ] ファイアウォール設定（必要に応じて）

**テスト:**
- [ ] hotelから `rsync rsync://fox.rewse.jp/homeassistant-config` で接続確認
- [ ] 設定ファイル一覧が取得できることを確認

**Demo:**
- [ ] rsync経由でfoxの設定ファイル一覧が取得できる

---

## Task 3: rsync同期設定（hotel側）

**目的:** hotelからfoxの設定ファイルを1分ごとに同期

**実装:**
- [ ] `/srv/homeassistant/config` ディレクトリを作成
- [ ] `roles/homeassistant-ha/files/homeassistant-sync.sh` を作成
- [ ] rsync同期スクリプト `/usr/local/bin/homeassistant-sync.sh` を配置
- [ ] `roles/homeassistant-ha/files/homeassistant-sync.service` を作成
- [ ] `roles/homeassistant-ha/files/homeassistant-sync.timer` を作成
- [ ] systemd service/timer を配置（1分ごとに実行）
- [ ] 初回同期を実行

**テスト:**
- [ ] タイマーを起動し、1分後に同期が実行されることを確認
- [ ] `journalctl -u homeassistant-sync.service` でログを確認

**Demo:**
- [ ] foxで設定ファイルを変更し、1分後にhotelに反映される

---

## Task 4: hotel側のDocker Compose設定

**目的:** hotelの `/etc/compose.yml` にhomeassistantセクションを追加

**実装:**
- [ ] `roles/homeassistant/tasks/main.yml` を修正し、hotelにも適用可能にする
- [ ] hotelでコンテナをpullするが、起動はしない（`state: present`）
- [ ] 必要なディレクトリ、証明書、設定ファイルを配置
- [ ] hotelに `singleton_int2` グループ変数を追加（必要に応じて）

**テスト:**
- [ ] `docker compose -f /etc/compose.yml config` でエラーがないことを確認
- [ ] hotelで手動で `docker compose up homeassistant` を実行し、起動することを確認
- [ ] 起動後、`docker compose stop homeassistant` で停止

**Demo:**
- [ ] hotelで手動で `docker compose up homeassistant` を実行し、起動することを確認（その後停止）

---

## Task 5: ヘルスチェックスクリプト作成（hotel側）

**目的:** foxのHome Assistantの状態を監視し、異常時にフェイルオーバー

**実装:**
- [ ] `roles/homeassistant-ha/files/homeassistant-failover.sh` を作成
- [ ] `/usr/local/bin/homeassistant-failover.sh` を配置
- [ ] チェックロジックを実装:
  - [ ] foxのAPI（http://fox.rewse.jp:8123/api/）をcurlで確認
  - [ ] 失敗したら30秒待機して再チェック
  - [ ] 2回連続失敗したら、SSH経由で `docker ps | grep homeassistant` を実行
  - [ ] コンテナが停止していたら、hotelで `docker compose up -d homeassistant` を実行
  - [ ] メール通知を送信
- [ ] ロックファイル `/var/run/homeassistant-failover.lock` で二重実行を防止

**テスト:**
- [ ] スクリプトを手動実行し、正常系の動作を確認（foxが稼働中）
- [ ] foxのコンテナを停止し、異常系の動作を確認
- [ ] ロックファイルが正しく動作することを確認

**Demo:**
- [ ] foxのコンテナを停止し、スクリプトが自動的にhotelで起動することを確認

---

## Task 6: systemd timer設定（hotel側）

**目的:** ヘルスチェックスクリプトを30秒ごとに実行

**実装:**
- [ ] `roles/homeassistant-ha/files/homeassistant-failover.service` を作成
- [ ] `roles/homeassistant-ha/files/homeassistant-failover.timer` を作成
- [ ] systemd service `/etc/systemd/system/homeassistant-failover.service` を配置
- [ ] systemd timer `/etc/systemd/system/homeassistant-failover.timer` を配置（30秒ごと）
- [ ] タイマーを有効化

**テスト:**
- [ ] タイマーを起動: `systemctl start homeassistant-failover.timer`
- [ ] タイマーの状態を確認: `systemctl status homeassistant-failover.timer`
- [ ] ログで定期実行を確認: `journalctl -u homeassistant-failover.service -f`

**Demo:**
- [ ] foxが正常稼働中は何も起こらず、停止すると自動的にフェイルオーバーが発生

---

## Task 7: メール通知設定

**目的:** フェイルオーバー発生時にメール通知

**実装:**
- [ ] ヘルスチェックスクリプトにメール送信処理を追加
- [ ] 既存のpostfix設定を利用（`roles/postfix/client`）
- [ ] 通知内容を実装:
  - [ ] 件名: `[ALERT] Home Assistant Failover: fox -> hotel`
  - [ ] 本文: フェイルオーバー発生時刻、理由、現在の状態
- [ ] 通知先メールアドレスを設定（group_vars等）

**テスト:**
- [ ] スクリプトから手動でメール送信を実行
- [ ] メールが正しく届くことを確認

**Demo:**
- [ ] フェイルオーバー発生時にメールが届く

---

## Task 8: Ansible Playbookの統合

**目的:** 全ての設定をAnsibleで管理

**実装:**
- [ ] `roles/homeassistant-ha/` ロールを作成
- [ ] `roles/homeassistant-ha/tasks/main.yml` でfox/hotel別の処理を分岐
- [ ] `roles/homeassistant-ha/handlers/main.yml` を作成
- [ ] `singleton_int1.yml` に `homeassistant-ha` ロールを追加
- [ ] `singleton_int2.yml` に `homeassistant-ha` ロールを追加
- [ ] タグ設定: `homeassistant-ha`, `homeassistant-ha-sync`, `homeassistant-ha-failover`

**テスト:**
- [ ] `ansible-playbook site.yml --tags homeassistant-ha --check` でドライラン
- [ ] エラーがないことを確認
- [ ] `ansible-playbook site.yml --tags homeassistant-ha --limit fox.rewse.jp` でfoxに適用
- [ ] `ansible-playbook site.yml --tags homeassistant-ha --limit hotel.rewse.jp` でhotelに適用

**Demo:**
- [ ] Ansibleで全体を適用し、HA構成が完成

---

## 完了条件

全てのタスクが完了し、以下の状態になっていること：

- [ ] foxでrsync daemonが稼働し、設定ファイルが公開されている
- [ ] hotelで1分ごとに設定ファイルが同期されている
- [ ] hotelでHome Assistantコンテナが準備されている（停止状態）
- [ ] hotelで30秒ごとにヘルスチェックが実行されている
- [ ] foxのコンテナを停止すると、自動的にhotelで起動する
- [ ] フェイルオーバー発生時にメール通知が送信される
- [ ] 全ての設定がAnsibleで管理されている
- [ ] ドキュメントが整備されている
