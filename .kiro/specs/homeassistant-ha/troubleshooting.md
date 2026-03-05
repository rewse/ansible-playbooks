# Home Assistant High Availability - トラブルシューティング

## よくある問題と解決方法

### 1. rsync同期が失敗する

#### 症状
- Zabbixアラート: "rsync同期が5分以上実行されていない"
- hotelの設定ファイルが更新されない

#### 原因と解決方法

**原因1: foxのrsync daemonが停止している**

確認方法:
```bash
# foxで実行
sudo systemctl status rsync
```

解決方法:
```bash
# foxで実行
sudo systemctl start rsync
sudo systemctl enable rsync
```

**原因2: ネットワーク接続の問題**

確認方法:
```bash
# hotelで実行
ping fox.rewse.jp
telnet fox.rewse.jp 873
```

解決方法:
- ネットワーク設定を確認
- ファイアウォール設定を確認

**原因3: 設定ファイルのパーミッション問題**

確認方法:
```bash
# foxで実行
ls -ld /srv/homeassistant/config
```

解決方法:
```bash
# foxで実行
sudo chmod 755 /srv/homeassistant/config
```

---

### 2. ヘルスチェックが誤検知する

#### 症状
- foxのHome Assistantは正常に動作しているのに、hotelでフェイルオーバーが発生する

#### 原因と解決方法

**原因1: APIの一時的な遅延**

確認方法:
```bash
# hotelで実行
time curl -s http://fox.rewse.jp:8123/api/
```

解決方法:
- ヘルスチェックスクリプトのタイムアウト値を調整
- リトライ回数を増やす

**原因2: ネットワークの一時的な切断**

確認方法:
```bash
# hotelで実行
sudo journalctl -u homeassistant-failover.service -n 100
```

解決方法:
- ヘルスチェックの間隔を調整（30秒 → 60秒）
- リトライ待機時間を延長（30秒 → 60秒）

**原因3: SSH接続の失敗**

確認方法:
```bash
# hotelで実行
ssh ubuntu@fox.rewse.jp "docker ps | grep homeassistant"
```

解決方法:
- SSH鍵の設定を確認
- `~/.ssh/known_hosts` を更新

---

### 3. hotelでHome Assistantが起動しない

#### 症状
- フェイルオーバーが実行されたが、hotelでHome Assistantが起動しない

#### 原因と解決方法

**原因1: Dockerイメージがpullされていない**

確認方法:
```bash
# hotelで実行
docker images | grep home-assistant
```

解決方法:
```bash
# hotelで実行
cd /etc
sudo docker compose pull homeassistant
```

**原因2: 設定ファイルが同期されていない**

確認方法:
```bash
# hotelで実行
ls -lh /srv/homeassistant/config/
```

解決方法:
```bash
# hotelで実行
sudo /usr/local/bin/homeassistant-sync.sh
```

**原因3: デバイスマッピングの問題**

確認方法:
```bash
# hotelで実行
ls -l /dev/ttyUSB0
```

解決方法:
- `/etc/compose.yml` のデバイスマッピングをコメントアウト
- または、hotelにUSBデバイスを接続

**原因4: ポート競合**

確認方法:
```bash
# hotelで実行
sudo netstat -tlnp | grep 8123
```

解決方法:
- 競合しているプロセスを停止
- または、Home Assistantのポートを変更

---

### 4. 設定ファイルの差分が発生する

#### 症状
- fox復旧時に設定ファイルの差分が大きい
- hotelでの設定変更がfoxに反映されない

#### 原因と解決方法

**原因: フェイルオーバー中にhotelで設定変更した**

確認方法:
```bash
# hotelで実行
rsync -avn --delete /srv/homeassistant/config/ rsync://fox.rewse.jp/homeassistant-config/
```

解決方法:
```bash
# hotelで実行
# 1. hotelの設定をバックアップ
sudo tar czf /tmp/hotel-config-backup.tar.gz /srv/homeassistant/config/

# 2. 差分を確認して手動でマージ
# 例: .storage/lovelace ファイルをfoxにコピー
scp /srv/homeassistant/config/.storage/lovelace ubuntu@fox.rewse.jp:/tmp/
ssh ubuntu@fox.rewse.jp "sudo cp /tmp/lovelace /srv/homeassistant/config/.storage/"
```

---

### 5. メール通知が届かない

#### 症状
- フェイルオーバーが発生したが、メール通知が届かない

#### 原因と解決方法

**原因1: postfixが停止している**

確認方法:
```bash
# hotelで実行
sudo systemctl status postfix
```

解決方法:
```bash
# hotelで実行
sudo systemctl start postfix
sudo systemctl enable postfix
```

**原因2: メールアドレスの設定ミス**

確認方法:
```bash
# hotelで実行
grep -r "MAILTO" /usr/local/bin/homeassistant-failover.sh
```

解決方法:
- スクリプト内のメールアドレスを修正

**原因3: メール送信のテスト**

確認方法:
```bash
# hotelで実行
echo "Test mail" | mail -s "Test" your-email@example.com
```

解決方法:
- postfixの設定を確認
- `/var/log/mail.log` を確認

---

### 6. Zabbix監視が動作しない

#### 症状
- Zabbixでホストが監視されていない
- アラートが発生しない

#### 原因と解決方法

**原因1: Zabbix Agentが停止している**

確認方法:
```bash
# hotelで実行
sudo systemctl status zabbix-agent2
```

解決方法:
```bash
# hotelで実行
sudo systemctl start zabbix-agent2
sudo systemctl enable zabbix-agent2
```

**原因2: Zabbixサーバーとの通信ができない**

確認方法:
```bash
# hotelで実行
telnet fox.rewse.jp 10051
```

解決方法:
- ファイアウォール設定を確認
- Zabbixサーバーの設定を確認

**原因3: 監視アイテムの設定ミス**

確認方法:
- Zabbix WebUIで監視アイテムの状態を確認

解決方法:
- 監視アイテムのキーを修正
- テンプレートを再適用

---

### 7. フェイルオーバー後にfoxに戻せない

#### 症状
- foxを起動してもHome Assistantが起動しない
- hotelとfoxの両方でHome Assistantが起動してしまう

#### 原因と解決方法

**原因1: フェイルオーバー監視が停止していない**

確認方法:
```bash
# hotelで実行
sudo systemctl status homeassistant-failover.timer
```

解決方法:
```bash
# hotelで実行
sudo systemctl stop homeassistant-failover.timer
```

**原因2: hotelのコンテナが停止していない**

確認方法:
```bash
# hotelで実行
docker ps | grep homeassistant
```

解決方法:
```bash
# hotelで実行
cd /etc
sudo docker compose stop homeassistant
```

**原因3: foxの設定ファイルが破損している**

確認方法:
```bash
# foxで実行
sudo docker compose logs homeassistant
```

解決方法:
```bash
# foxで実行
# hotelから設定ファイルをコピー
rsync -av ubuntu@hotel.rewse.jp:/srv/homeassistant/config/ /srv/homeassistant/config/
```

---

## デバッグ手順

### 1. ログの確認

```bash
# systemdサービスのログ
sudo journalctl -u homeassistant-sync.service -n 100
sudo journalctl -u homeassistant-failover.service -n 100

# Dockerコンテナのログ
docker compose logs homeassistant --tail 100

# システムログ
sudo tail -f /var/log/syslog | grep homeassistant
```

### 2. 手動でのテスト実行

```bash
# rsync同期のテスト
sudo /usr/local/bin/homeassistant-sync.sh

# ヘルスチェックのテスト
sudo /usr/local/bin/homeassistant-failover.sh

# Home Assistantの起動テスト
cd /etc
sudo docker compose up homeassistant
```

### 3. ネットワーク接続の確認

```bash
# foxへの接続確認
ping fox.rewse.jp
telnet fox.rewse.jp 873   # rsync
telnet fox.rewse.jp 8123  # Home Assistant API
ssh ubuntu@fox.rewse.jp   # SSH
```

---

## エスカレーション

以下の場合は、システム管理者にエスカレーションする：

- [ ] foxのハードウェア障害が疑われる
- [ ] ネットワーク全体の障害が疑われる
- [ ] データベース（Aurora）の障害が疑われる
- [ ] 上記のトラブルシューティングで解決しない

---

## 緊急連絡先

- システム管理者: [連絡先を記載]
- ネットワーク管理者: [連絡先を記載]
- データベース管理者: [連絡先を記載]
