---
inclusion: always
---

# 技術スタック

## コア技術
- **Ansible**: 構成管理のための主要な自動化ツール
- **YAML**: プレイブック、ロール、変数定義に使用
- **Jinja2**: 動的構成ファイルのためのテンプレートエンジン
- **direnv**: ディレクトリベースの環境変数管理
- **1Password CLI**: 機密情報の安全な保存と取得のため
- **1Password Environments**: 環境変数の安全な管理とローカル `.env` ファイルマウント

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

### direnv
このプロジェクトでは、direnv を使用してディレクトリベースの環境変数管理を行っている。

#### 仕組み
- ディレクトリに入ると自動的に `.envrc` ファイルを読み込む
- ディレクトリから出ると環境変数を自動的にアンロード
- セキュリティのため、`.envrc` の変更時には `direnv allow` で明示的な承認が必要

#### 使用方法
```bash
# .envrc の変更を承認
direnv allow

# direnv の状態を確認
direnv status
```

このプロジェクトの `.envrc` では、1Password Environments の `.env` ファイルを読み込んでいる：
```bash
set -a
source .env
set +a
```

- `set -a`: 以降の変数を自動的に環境変数としてエクスポート
- `source .env`: `.env` ファイルを読み込む
- `set +a`: 自動エクスポートを解除

**注意**: direnv の `dotenv` コマンドは UNIX 名前付きパイプに対応していないため、`source` コマンドを使用している。

#### 詳細情報
- [direnv 公式サイト](https://direnv.net/)

### 1Password Environments
このプロジェクトでは、1Password Environments を使用して環境変数を安全に管理している。

#### 仕組み
- 1Password が `.env` ファイルを UNIX 名前付きパイプとしてマウント
- ファイルの内容は平文でディスクに保存されず、読み取り時にオンデマンドで提供される
- 1Password がロックされるまで認証が持続し、複数のプロセスから読み取り可能

#### 設定方法
1. 1Password デスクトップアプリで Developer 機能を有効化
2. 新しい Environment を作成
3. 環境変数（キー・バリューペア）を追加
4. Destinations タブから「Local `.env` file」を設定
5. マウント先のパスを選択（このプロジェクトでは `.env`）

#### 使用方法
初回読み取り時に 1Password の認証プロンプトが表示される。

#### 詳細情報
- [1Password Environments ドキュメント](https://developer.1password.com/docs/environments/)
- [ローカル .env ファイルマウント](https://developer.1password.com/docs/environments/local-env-file)

### ベストプラクティス
- 選択的な実行にはタグを常に使用する
- 機密データは 1Password に保管し、`lookup('pipe', 'op read ...')` で参照する
- 共有設定には group_vars を使用する
- 変更を適用する前に --check で確認する
- ロール固有の変数は role/vars ディレクトリに保持する
- Ansible 実行前に `op signin` で 1Password に認証しておく
