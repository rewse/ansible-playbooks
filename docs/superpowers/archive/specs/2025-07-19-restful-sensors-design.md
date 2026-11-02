# 設計ドキュメント

## 概要

このドキュメントでは、REGZA テレビの3つのセンサー（音量ミュート状態、チャンネル情報、コンテンツタイプ）を command_line センサーから RESTful センサーに変更するための設計を定義します。RESTful センサーを使用することで、HTTP リクエストの処理がより効率的になり、Home Assistant のパフォーマンスが向上します。

## アーキテクチャ

現在の実装では、command_line センサーが curl コマンドを実行して REGZA の API からデータを取得しています。新しい実装では、Home Assistant の RESTful センサー統合を使用して直接 HTTP リクエストを行います。

### 現在のアーキテクチャ

```
Home Assistant → command_line センサー → curl コマンド → REGZA API → データ取得 → jq による処理 → センサー値
```

### 新しいアーキテクチャ

```
Home Assistant → RESTful センサー → REGZA API → データ取得 → Jinja2 テンプレートによる処理 → センサー値
```

## コンポーネントとインターフェース

### RESTful センサーの構成

RESTful センサーは以下のコンポーネントで構成されます：

1. **REST リソース**: REGZA API のエンドポイントを指定
2. **認証**: ダイジェスト認証の設定
3. **Jinja2 テンプレート**: レスポンスから必要なデータを抽出するための式
4. **センサー属性**: 名前、一意のID、スキャン間隔などの設定

### インターフェース

REGZA API は以下のエンドポイントを提供しています：

1. **ミュート状態**: `http://regza/v2/remote/status/mute`
2. **再生状態**: `http://regza.rewse.jp/v2/remote/play/status`

## データモデル

### RESTful センサーの設定

```yaml
binary_sensor:
  - platform: rest
    name: "REGZA Volume Muted"
    unique_id: binary_sensor.regza_volume_muted
    resource: http://regza/v2/remote/status/mute
    authentication: digest
    username: !secret regza_username
    password: !secret regza_password
    value_template: "{{ value_json.mute == 'on' }}"
    device_class: sound

sensor:
  - platform: rest
    name: "REGZA Channel"
    unique_id: sensor.regza_channel
    resource: http://regza.rewse.jp/v2/remote/play/status
    authentication: digest
    username: !secret regza_username
    password: !secret regza_password
    value_template: "{{ value_json.epg_info_current.channel_name }}"
    
  - platform: rest
    name: "REGZA Content Type"
    unique_id: sensor.regza_content_type
    resource: http://regza.rewse.jp/v2/remote/play/status
    authentication: digest
    username: !secret regza_username
    password: !secret regza_password
    value_template: "{{ value_json.content_type }}"
    scan_interval: 5
```

### レスポンスデータ構造

1. **ミュート状態**:
```json
{
  "status": 0,
  "mute": "on"|"off"
}
```

2. **再生状態**:
```json
{
  "status": 0,
  "content_type": "broadcast",
  "epg_info_current": {
    "channel_number": 11,
    "channel_name": "ＮＨＫ総合１・東京",
    // その他の情報
  },
  // その他の情報
}
```

## エラー処理

RESTful センサーは以下のエラー処理を実装します：

1. **接続エラー**: REGZA に接続できない場合、センサーは `unavailable` 状態になります
2. **認証エラー**: 認証情報が無効な場合、エラーログに記録されます
3. **データ解析エラー**: Jinja2 テンプレートが有効なデータを見つけられない場合、センサーは `unknown` 状態になります

## テスト戦略

以下のテストを実施して、RESTful センサーの正常な動作を確認します：

1. **機能テスト**:
   - 各センサーが正しいデータを取得できることを確認
   - ミュート状態の変更が正しく反映されることを確認
   - チャンネル変更が正しく反映されることを確認
   - コンテンツタイプの変更が正しく反映されることを確認

2. **エラー処理テスト**:
   - REGZA が利用できない場合の動作を確認
   - 認証エラーの場合の動作を確認
   - 無効なレスポンスの場合の動作を確認

3. **パフォーマンステスト**:
   - command_line センサーと比較して、リソース使用量が改善されていることを確認
   - スキャン間隔が正しく設定されていることを確認

## 実装の注意点

1. **認証情報の管理**:
   - REGZA の認証情報は Home Assistant の secrets.yaml に保存し、テンプレートから参照します
   - 現在の Jinja2 テンプレート変数 `[% regza.username %]` と `[% regza.password %]` を Home Assistant の secrets 形式に変換します
   - `roles/homeassistant/templates/secrets.yaml.j2` に以下の設定を追加します：
     ```yaml
     # REGZA API 認証情報
     regza_username: '[% vault_regza.username %]'
     regza_password: '[% vault_regza.password %]'
     ```

2. **互換性の確保**:
   - センサーの unique_id と名前は既存のものを維持し、自動化やスクリプトの互換性を確保します
   - バイナリセンサーとして実装されていたものは、RESTful センサーでもバイナリセンサーとして実装します

3. **スキャン間隔**:
   - コンテンツタイプセンサーの特別なスキャン間隔（5秒）を維持します
   - 他のセンサーはデフォルトのスキャン間隔を使用します
