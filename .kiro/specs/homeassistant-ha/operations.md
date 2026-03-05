# Home Assistant High Availability - 運用手順

## 日常運用

### 監視項目（Zabbix）

以下の項目をZabbixで監視する：

#### 1. rsync同期の状態（hotel）

**監視項目:**
- `systemd.unit.state[homeassistant-sync.service]` - サービスの状態
- `systemd.unit.active_time[homeassistant-sync.service]` - 最終実行時刻
- `vfs.file.time[/srv/homeassistant/config/configuration.yaml,modify]` - 設定ファイルの最終更新時刻

**アラート条件:**
- rsync同期が5分以上実行されていない
- 設定ファイルが10分以上更新されていない

#### 2. ヘルスチェックの状態（hotel）

**監視項目:**
- `systemd.unit.state[homeassistant-failover.timer]` - タイマーの状態
- `systemd.unit.state[homeassistant-failover.service]` - サービスの状態
- `log[/var/log/syslog,homeassistant-failover]` - ログ監視

**アラート条件:**
- フェイルオーバータイマーが停止している
- フェイルオーバーが実行された（ログに "Failover triggered" が出力）

#### 3. Home Assistantの稼働状態（fox）

**監視項目:**
- `docker.container_info[homeassistant,State.Running]` - コンテナの稼働状態
- `net.tcp.service[http,fox.rewse.jp,8123]` - APIポートの応答
- `web.page.get[fox.rewse.jp,/api/,8123]` - API応答の確認

**アラート条件:**
- コンテナが停止している
- APIが応答しない

#### 4. 設定ファイルの同期状態（fox/hotel）

**監視項目:**
- `vfs.dir.size[/srv/homeassistant/config]` - 設定ディレクトリのサイズ（fox/hotel）
- カスタムスクリプトで差分チェック

**アラート条件:**
- fox/hotel間でディレクトリサイズが大きく異なる（10%以上）

### 手動確認（トラブル時）

Zabbixのアラートが発生した場合、以下のコマンドで詳細を確認：

1. **rsync同期の状態**
   ```bash
   # hotelで実行
   sudo journalctl -u homeassistant-sync.service --since "1 hour ago"
   ```

2. **ヘルスチェックの状態**
   ```bash
   # hotelで実行
   sudo journalctl -u homeassistant-failover.service --since "1 hour ago"
   ```

3. **Home Assistantの稼働状態**
   ```bash
   # foxで実行
   docker ps | grep homeassistant
   curl -s http://fox.rewse.jp:8123/api/ | jq .
   ```

4. **設定ファイルの同期状態**
   ```bash
   # hotelで実行
   ls -lh /srv/homeassistant/config/
   ```

## フェイルオーバー発生時の対応

### 1. フェイルオーバーの確認

メール通知を受信したら、以下を確認する：

```bash
# hotelで実行
docker ps | grep homeassistant
curl -s http://hotel.rewse.jp:8123/api/ | jq .
```

**注意:** foxが停止しているため、Zabbixも停止している。手動確認が必要。

### 2. foxの状態確認

```bash
# foxで実行（SSH接続可能な場合）
docker ps | grep homeassistant
sudo journalctl -u docker.service --since "1 hour ago"
```

### 3. Home Assistantの動作確認

- ブラウザで `https://hass.rewse.jp/` にアクセス
- ダッシュボードが表示されることを確認
- センサーデータが更新されていることを確認
- オートメーションが動作していることを確認

### 4. 原因調査

foxがダウンした原因を調査する：

- ハードウェア障害
- ネットワーク障害
- Dockerコンテナのクラッシュ
- システムリソース不足

## 手動復旧（foxへの切り戻し）

### 前提条件

- foxが復旧していること
- foxのHome Assistantコンテナが起動可能な状態であること

### 手順

#### 1. フェイルオーバー監視を停止

```bash
# hotelで実行
sudo systemctl stop homeassistant-failover.timer
sudo systemctl status homeassistant-failover.timer
```

#### 2. 設定ファイルの差分確認

```bash
# hotelで実行
rsync -avn --delete /srv/homeassistant/config/ rsync://fox.rewse.jp/homeassistant-config/
```

差分がある場合は、以下のいずれかを選択：
- **a. hotelの設定を破棄:** 何もしない（foxの設定が優先される）
- **b. hotelの設定をfoxにマージ:** 手動でファイルをコピー

#### 3. hotelのHome Assistantを停止

```bash
# hotelで実行
cd /etc
sudo docker compose stop homeassistant
sudo docker compose ps | grep homeassistant
```

#### 4. foxのHome Assistantを起動

```bash
# foxで実行
cd /etc
sudo docker compose up -d homeassistant
sudo docker compose ps | grep homeassistant
```

#### 5. foxの動作確認

```bash
# foxで実行
curl -s http://fox.rewse.jp:8123/api/ | jq .
```

ブラウザで `https://hass.rewse.jp/` にアクセスし、正常に動作することを確認。

#### 6. Zabbixの復旧確認

foxが起動したことで、Zabbixサーバーも復旧する。Zabbixの監視が正常に動作していることを確認。

#### 7. フェイルオーバー監視を再開

```bash
# hotelで実行
sudo systemctl start homeassistant-failover.timer
sudo systemctl status homeassistant-failover.timer
```

#### 8. 復旧完了の確認

```bash
# hotelで実行
sudo journalctl -u homeassistant-failover.service -f
```

ヘルスチェックが正常に動作していることを確認。

## 設定変更時の注意点

### foxで設定変更する場合（通常運用）

1. foxのHome Assistantで設定変更
2. 1分以内にhotelに自動同期される
3. 特別な操作は不要

### hotelで設定変更する場合（フェイルオーバー中）

**警告:** フェイルオーバー中にhotelで設定変更すると、fox復旧時に上書きされる可能性がある。

**推奨手順:**

1. hotelで設定変更
2. 変更内容をメモまたはバックアップ
3. fox復旧時に手動でマージ

**バックアップ方法:**

```bash
# hotelで実行
sudo tar czf /tmp/homeassistant-config-backup-$(date +%Y%m%d-%H%M%S).tar.gz /srv/homeassistant/config/
```

## フェイルオーバーのテスト

定期的にフェイルオーバーをテストすることを推奨する。

### テスト手順

#### 1. 事前確認

```bash
# foxで実行
docker ps | grep homeassistant

# hotelで実行
docker ps | grep homeassistant  # 停止していることを確認
```

#### 2. foxのコンテナを停止

```bash
# foxで実行
cd /etc
sudo docker compose stop homeassistant
```

**注意:** Zabbixもfoxで動いているため、この時点でZabbix監視も停止する。

#### 3. フェイルオーバーの確認

約2分待機し、hotelでコンテナが起動することを確認：

```bash
# hotelで実行
docker ps | grep homeassistant
curl -s http://hotel.rewse.jp:8123/api/ | jq .
```

#### 4. メール通知の確認

フェイルオーバー通知メールが届くことを確認。

#### 5. 復旧テスト

「手動復旧（foxへの切り戻し）」の手順に従って復旧。

## トラブル時の緊急対応

### hotelでHome Assistantが起動しない場合

```bash
# hotelで実行
cd /etc
sudo docker compose logs homeassistant
sudo docker compose up homeassistant  # フォアグラウンドで起動してログ確認
```

### rsync同期が失敗する場合

```bash
# hotelで実行
rsync -av rsync://fox.rewse.jp/homeassistant-config/ /tmp/test/  # テスト同期
sudo journalctl -u homeassistant-sync.service -n 50
```

### ヘルスチェックが誤検知する場合

```bash
# hotelで実行
sudo systemctl stop homeassistant-failover.timer
sudo /usr/local/bin/homeassistant-failover.sh  # 手動実行してデバッグ
```

## 定期メンテナンス

### 月次

- [ ] フェイルオーバーのテスト実施
- [ ] ログの確認とクリーンアップ
- [ ] 設定ファイルのバックアップ
- [ ] Zabbixの監視項目の見直し

### 四半期

- [ ] ドキュメントの見直し
- [ ] 運用手順の改善
- [ ] パフォーマンスの確認

### 年次

- [ ] HA構成の見直し
- [ ] ハードウェアの更新検討
- [ ] セキュリティ監査
