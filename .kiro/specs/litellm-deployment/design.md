# Design Document

## Overview

このドキュメントでは、LiteLLMプロキシサーバーをDockerコンテナとしてデプロイし、AWS Bedrockとの統合を提供するAnsibleロールの設計について説明します。LiteLLMは統一されたOpenAI互換APIを通じてAWS Bedrockの複数のLLMモデルへのアクセスを可能にします。

## Architecture

### システム構成

```mermaid
graph LR
    CLIENT[クライアント<br/>アプリケーション] --> LITELLM[LiteLLM Proxy<br/>Docker Container<br/>:4000]
    LITELLM --> BEDROCK[AWS Bedrock<br/>Claude Models]
    
    ANSIBLE[Ansible Role] --> COMPOSE[/etc/compose.yml]
    ANSIBLE --> CONFIG[/srv/litellm/config.yaml]
    COMPOSE --> LITELLM
    CONFIG --> LITELLM
    
    classDef client fill:#e1f5fe
    classDef proxy fill:#f3e5f5
    classDef aws fill:#fff3e0
    classDef config fill:#e8f5e8
    
    class CLIENT client
    class LITELLM proxy
    class BEDROCK aws
    class ANSIBLE,CONFIG,COMPOSE config
```

### コンポーネント概要

1. **LiteLLM Dockerコンテナ**: 公式イメージ（ghcr.io/berriai/litellm:main-stable）を使用
2. **設定ファイル**: AWS Bedrockモデルの設定を含むconfig.yaml
3. **環境変数**: AWS認証情報とLiteLLMセキュリティキー
4. **ボリュームマウント**: 設定ファイルのホストからコンテナへのマウント

## Components and Interfaces

### 1. Ansibleロール構造

```
roles/litellm/
├── tasks/
│   └── main.yml              # メインタスク（ディレクトリ作成、設定生成、Compose追記）
├── templates/
│   └── config.yaml.j2        # LiteLLM設定テンプレート（推論プロファイル形式）
├── handlers/
│   └── main.yml              # LiteLLMコンテナ再起動ハンドラー
└── vars/
    └── main.yml              # ロール変数（Vault参照による機密情報）
```

**各ファイルの役割：**
- `tasks/main.yml`: ディレクトリ作成、設定ファイル生成、Docker Compose設定追記（タグ付き）
- `templates/config.yaml.j2`: Claude 3.7 Sonnet, Claude Sonnet 4, Claude Opus 4の推論プロファイル設定
- `handlers/main.yml`: 設定変更時のLiteLLMコンテナ個別再起動（エラーハンドリング付き）
- `vars/main.yml`: AWS認証情報とLiteLLMセキュリティキーのVault参照

### 2. Docker Compose統合

`ansible.builtin.blockinfile`を使用して/etc/compose.ymlファイルに設定を追記します：

```yaml
# Ansibleタスクでの実装
- name: Add LiteLLM service to Docker Compose
  ansible.builtin.blockinfile:
    path: /etc/compose.yml
    marker: "# {mark} ANSIBLE MANAGED BLOCK litellm"
    block: |2
        litellm:
          container_name: litellm
          image: ghcr.io/berriai/litellm:main-stable
          ports:
            - "4000:4000"
          volumes:
            - /srv/litellm/config.yaml:/app/config.yaml:ro
          environment:
            - AWS_ACCESS_KEY_ID={{ litellm_aws_access_key_id }}
            - AWS_SECRET_ACCESS_KEY={{ litellm_aws_secret_access_key }}
            - AWS_REGION_NAME=us-east-1
            - LITELLM_MASTER_KEY={{ litellm_master_key }}
            - LITELLM_SALT_KEY={{ litellm_salt_key }}
          restart: unless-stopped
          command: ["--config", "/app/config.yaml", "--port", "4000"]
  notify: Restart litellm
  tags: [litellm, docker]
```

**設定のポイント：**
- `block: |2` でインデントを調整してYAML構造を維持
- `marker` でAnsible管理ブロックを明示
- 固定値（ポート4000、リージョンus-east-1）は直接記述
- 機密情報（AWS認証情報、LiteLLMキー）のみ変数参照を使用
- 設定変更時は `Restart litellm` ハンドラーで個別コンテナを再起動

### 3. 設定ファイルテンプレート

config.yaml.j2テンプレートは固定のモデル設定を含みます：

```yaml
model_list:
  - model_name: claude-3-7-sonnet
    litellm_params:
      model: bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0
      aws_region_name: us-east-1
  - model_name: claude-sonnet-4
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0
      aws_region_name: us-east-1
  - model_name: claude-opus-4
    litellm_params:
      model: bedrock/us.anthropic.claude-opus-4-20250514-v1:0
      aws_region_name: us-east-1
```

モデル設定は推論プロファイル形式を使用し、サポートされているモデルのみを含めます。

### 4. 実装アプローチ

以下の手順でLiteLLMをデプロイします：

1. **ディレクトリ作成**: `/srv/litellm`ディレクトリの作成（`owner: root, group: root`）
2. **設定ファイル生成**: `config.yaml.j2`テンプレートから`/srv/litellm/config.yaml`を生成（`owner: root, group: root`）
3. **Compose設定追記**: `/etc/compose.yml`への`blockinfile`による追記
4. **LiteLLMコンテナ再起動**: `Restart litellm`ハンドラーによる個別コンテナ再起動

**タグ構成：**
- `tags: [litellm, config]`: ディレクトリ作成と設定ファイル生成
- `tags: [litellm, docker]`: Docker Compose設定追記

### 5. 環境変数管理

環境変数は/etc/compose.ymlの環境変数セクションで管理されます：

- `AWS_ACCESS_KEY_ID`: AWS認証情報
- `AWS_SECRET_ACCESS_KEY`: AWS認証情報  
- `AWS_REGION_NAME`: AWSリージョン
- `LITELLM_MASTER_KEY`: LiteLLMマスターキー
- `LITELLM_SALT_KEY`: 暗号化用ソルトキー

これらの値はAnsible Vaultで暗号化され、テンプレート内で参照されます。

## Data Models

### 1. Ansible変数構造

Vault参照が必要な機密情報のみを変数として定義：

```yaml
# 機密情報（Vault参照）
litellm_aws_access_key_id: "{{ vault_litellm.aws.access_key }}"
litellm_aws_secret_access_key: "{{ vault_litellm.aws.secret_access_key }}"
litellm_master_key: "{{ vault_litellm.master_key }}"
litellm_salt_key: "{{ vault_litellm.salt_key }}"
```

その他の設定値（ポート、イメージ名、ディレクトリパス、モデル設定など）は、tasksファイル内に直接記述されます。

### 2. 設定ファイル構造

config.yamlは以下の3つのClaudeモデルを含む形式で生成されます：

```yaml
model_list:
  - model_name: claude-3-7-sonnet
    litellm_params:
      model: bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0
      aws_region_name: us-east-1
  - model_name: claude-sonnet-4
    litellm_params:
      model: bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0
      aws_region_name: us-east-1
  - model_name: claude-opus-4
    litellm_params:
      model: bedrock/us.anthropic.claude-opus-4-20250514-v1:0
      aws_region_name: us-east-1
```

## Error Handling

### 1. ハンドラーエラー処理

実装されているエラーハンドリング：

```yaml
- name: Restart litellm
  ansible.builtin.command: docker compose -f /etc/compose.yml restart litellm
  register: litellm_restart_result
  failed_when: litellm_restart_result.rc != 0
```

- **コンテナ再起動失敗**: `failed_when` でリターンコードをチェック
- **実行結果の記録**: `register` で実行結果を保存

### 2. 基本的なファイル操作

- **ディレクトリ作成**: `/srv/litellm` ディレクトリの作成（`owner: root, group: root`）
- **設定ファイル生成**: テンプレートからの設定ファイル生成（`owner: root, group: root`）
- **Docker Compose設定**: blockinfileによる設定追記（マーカー付き）
- **タグによる選択実行**: `[litellm, config]` と `[litellm, docker]` でタスクを分類

## Testing Strategy

### 手動テスト

実際に実行可能なテスト方法：

```bash
# 1. コンテナ起動確認
sudo docker ps | grep litellm

# 2. モデル一覧の取得
curl -X GET "http://fox.rewse.jp:4000/v1/models" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# 3. Claude 3.7 Sonnetのテスト
curl -X POST "http://fox.rewse.jp:4000/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-7-sonnet",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# 4. AWS認証情報確認
sudo docker exec litellm env | grep AWS

# 5. ログ確認
sudo docker logs litellm
```

## セキュリティ考慮事項

### 実装済みのセキュリティ機能

- **Ansible Vault**: AWS認証情報とLiteLLMキーをVaultで暗号化
- **環境変数**: 機密情報は環境変数経由でコンテナに渡す
- **ファイル権限**: 設定ファイルに適切な所有者（root:root）を設定
- **認証**: LITELLM_MASTER_KEYによるAPI認証

## 運用考慮事項

### 基本的な運用手順

```bash
# コンテナ状態確認
sudo docker ps | grep litellm

# ログ確認
sudo docker logs litellm

# コンテナ再起動
sudo docker-compose -f /etc/compose.yml restart litellm

# 設定ファイル確認
sudo cat /srv/litellm/config.yaml

# AWS認証情報確認
sudo docker exec litellm env | grep AWS

# AWS認証情報の詳細確認（トラブルシューティング用）
echo "AWS_ACCESS_KEY_ID:"
sudo docker exec litellm printenv AWS_ACCESS_KEY_ID
echo "AWS_SECRET_ACCESS_KEY:"
sudo docker exec litellm printenv AWS_SECRET_ACCESS_KEY
echo "AWS_REGION_NAME:"
sudo docker exec litellm printenv AWS_REGION_NAME
```

### 設定変更時の手順

1. Ansibleプレイブックを実行
2. 自動的にコンテナが再起動される（ハンドラー）
3. 動作確認を実施
