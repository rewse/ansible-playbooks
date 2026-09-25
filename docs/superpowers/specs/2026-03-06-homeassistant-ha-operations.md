# Home Assistant High Availability - 運用手順

## 前提条件

HA 構成を動作させるために、以下の設定が必要：

- hotel の `tats` ユーザーから fox (port 11022) への公開鍵 SSH 認証
- fox の `tats` ユーザーが passwordless sudo を実行可能
- `group_vars/all/vars` の `email.primary` 変数（1Password 参照）に通知先メールアドレスが設定されている
- hotel の Ubuntu グループに `postfix/client` ロールが適用されている（`ubuntu.yml` 経由）

## API 応答の判定基準

Home Assistant の `/api/` エンドポイントは認証が必要で、認証なしのアクセスでは HTTP 401 を返す。
failover/failback スクリプトはこの 401 を「Home Assistant が応答している」と解釈する。

- **健全と判定**: HTTP 2xx / 3xx / 401 / 403
- **異常と判定**: 接続失敗、タイムアウト、5xx、その他

Zabbix 等で監視する場合、同じ判定基準に合わせること（単純な 2xx 判定では常に異常扱いになる）。

## 日常運用

### 監視項目（Zabbix）

以下の項目をZabbixで監視する。UserParameter は Ansible で配置済み
（`homeassistant-ha/primary/files/homeassistant-ha.conf`、
`homeassistant-ha/secondary/files/homeassistant-ha.conf`）。
Zabbix サーバー側の item / trigger 設定は Zabbix Web UI で手動登録する。

#### 1. rsync同期の状態（hotel）

**監視項目:**
- `homeassistant.sync.active[timer]` - タイマーの状態（`active` を期待）
- `homeassistant.sync.last_exit` - 直近実行の終了コード（`0` を期待）
- `vfs.file.time[/srv/homeassistant/config/configuration.yaml,modify]` - 設定ファイルの最終更新時刻

**アラート条件:**
- `sync.active[timer]` が `active` 以外
- `sync.last_exit` が `0` 以外
- 設定ファイルが10分以上更新されていない

#### 2. ヘルスチェックの状態（hotel）

**監視項目:**
- `homeassistant.failover.active[timer]` - タイマーの状態（`active` を期待）
- `homeassistant.failover.last_exit` - 直近実行の終了コード（`0` を期待）
- `homeassistant.failover.triggered[1h]` - 直近 1 時間のフェイルオーバー発動回数（時間窓は `5m`, `10m`, `1h`, `1d` などに変更可能）
- `homeassistant.container.running` - hotel の HA コンテナ状態（`false` を期待）

**アラート条件:**
- フェイルオーバータイマーが停止している
- `failover.triggered[1h]` が 0 より大きい（フェイルオーバー発動）
- `container.running` が `true`（hotel で HA が起動している = 要確認状態）

#### 3. Home Assistantの稼働状態（fox）

**監視項目:**
- `homeassistant.container.running` - fox の HA コンテナ状態（`true` を期待）
- `homeassistant.api.http_code` - HA API の HTTP ステータスコード
- `homeassistant.rsync.active` - rsync daemon の状態（`active` を期待）
- `net.tcp.service[http,fox.rewse.jp,8123]` - APIポートの応答

**アラート条件:**
- `container.running` が `false`
- `api.http_code` が 2xx / 3xx / 401 / 403 以外（500 系、`000`、その他）
- `rsync.active` が `active` 以外

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
   sudo docker ps | grep homeassistant
   # 401 が返れば HA は応答している
   curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://fox.rewse.jp:8123/api/
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
sudo docker ps | grep homeassistant
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://hotel.rewse.jp:8123/api/
```

**注意:** foxが停止しているため、Zabbixも停止している。手動確認が必要。

### 2. foxの状態確認

```bash
# foxで実行（SSH接続可能な場合）
sudo docker ps | grep homeassistant
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

## 復旧（foxへの切り戻し）

### 前提条件

- foxが復旧していること
- foxのHome Assistantコンテナが起動可能な状態であること
- hotel から fox への SSH 鍵認証が設定されていること

### スクリプトによる復旧（推奨）

hotel 側に `/usr/local/bin/homeassistant-failback` スクリプトが配置されている。
このスクリプトが以下の処理を自動で行う：

1. 前提条件のチェック（hotel で HA が起動中か、fox に SSH/rsync で到達可能か）
2. フェイルオーバータイマーの停止
3. 設定ファイルの差分表示
4. マージ方針の選択（push / discard / abort）
5. hotel の Home Assistant を停止
6. 設定ファイルを fox に push（push を選択した場合）
7. fox の Home Assistant を起動
8. fox の API が応答するまで最大 120 秒ポーリング
9. フェイルオーバータイマーの再開
10. 成功/失敗のメール通知

#### 対話モード（推奨）

```bash
# hotel で実行
sudo homeassistant-failback
```

差分が表示されたら、以下から選択する：

- `1` push: hotel の設定で fox を上書き（hotel 側で設定変更していた場合）
- `2` discard: hotel の変更を破棄（fox の元の設定で戻す）
- `3` abort: 復旧を中止してフェイルオーバータイマーを再開

#### 非対話モード

```bash
# hotel の設定を fox に反映
sudo homeassistant-failback --yes --merge push

# hotel の設定を破棄（fox の設定を維持）
sudo homeassistant-failback --yes --merge discard
```

#### スクリプトが失敗した場合

各ステップは失敗時に自動でフェイルオーバータイマーを再開してから終了するため、
hotel が再び監視を継続する状態に戻る。失敗理由は `journalctl -t homeassistant-failback` で確認できる。
対処後、再度スクリプトを実行するか、以下の手動復旧手順を参照する。

### 手動復旧（スクリプトが使えない場合）

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
sudo /usr/local/bin/homeassistant-failover  # 手動実行してデバッグ
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
