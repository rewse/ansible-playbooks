---
inclusion: always
---

# 技術スタック

## コア技術
- **Ansible**: 構成管理のための主要な自動化ツール
- **YAML**: プレイブック、ロール、変数定義に使用
- **Jinja2**: 動的構成ファイルのためのテンプレートエンジン
- **1Password CLI**: 機密情報の安全な保存と取得のため

## プラットフォーム
- **Ubuntu**: Linux サーバーとクラウドインスタンス
- **AWS EC2**: クラウドインフラストラクチャ
- **Raspberry Pi**: IoT とホームオートメーションデバイス
- **macOS**: 開発者ワークステーション（ビジネス用と個人用）

## サービスとアプリケーション
- **Web サーバー**: Apache HTTPD
- **データベース**: CouchDB
- **監視**: Zabbix
- **ホームオートメーション**: Home Assistant, MQTT (Mosquitto), Matter
- **IoT**: SwitchBot, MHZ19 センサー, Enecoq
- **クラウドサービス**: AWS 統合
- **セキュリティ**: certbot による SSL 証明書, SSH 設定

## 一般的なコマンド

### Ansible コマンド
```bash
# 全体のプレイブックを実行
ansible-playbook site.yml

# 特定のプレイブックを実行
ansible-playbook ubuntu.yml

# 特定のタグで実行
ansible-playbook ubuntu.yml --tags ubuntu,package

# チェックモード（ドライラン）
ansible-playbook site.yml --check

# 特定のホストに対して実行
ansible-playbook site.yml --limit "fox.rewse.jp"
```

### 1Password コマンド
```bash
# 1Password にサインイン
op signin

# 認証状態を確認
op whoami

# シークレットを読み取る（テスト用）
op read op://ansible/database/password

# Ansible での使用例
# プレイブックや vars ファイル内で:
# db_password: "{{ lookup('pipe', 'op read op://ansible/database/password') }}"
```

### ベストプラクティス
- 選択的な実行にはタグを常に使用する
- 機密データは 1Password に保管し、`lookup('pipe', 'op read ...')` で参照する
- 共有設定には group_vars を使用する
- 変更を適用する前に --check で確認する
- ロール固有の変数は role/vars ディレクトリに保持する
- Ansible 実行前に `op signin` で 1Password に認証しておく
