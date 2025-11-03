---
inclusion: always
---

# 技術スタック

## コア技術
- **Ansible**: 構成管理のための主要な自動化ツール
- **YAML**: プレイブック、ロール、変数定義に使用
- **Jinja2**: 動的構成ファイルのためのテンプレートエンジン
- **Vault**: 機密情報の安全な保存のため

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

# Vault パスワードで実行
ansible-playbook site.yml --ask-vault-pass

# チェックモード（ドライラン）
ansible-playbook site.yml --check

# 特定のホストに対して実行
ansible-playbook site.yml --limit "fox.rewse.jp"
```

### Vault コマンド
```bash
# Vault ファイルを編集
ansible-vault edit group_vars/all/vault

# 新しい Vault ファイルを作成
ansible-vault create new_vault_file.yml

# 既存のファイルを暗号化
ansible-vault encrypt plain_file.yml
```

### ベストプラクティス
- 選択的な実行にはタグを常に使用する
- 機密データは Vault ファイルに保管する
- 共有設定には group_vars を使用する
- 変更を適用する前に --check で確認する
- ロール固有の変数は role/vars ディレクトリに保持する
