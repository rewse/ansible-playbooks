# Requirements Document

## Introduction

LiteLLMは、OpenAI、Azure、Cohere、Anthropic、Huggingface、Replicateなど100以上のLLMプロバイダーに対して統一されたAPIインターフェースを提供するプロキシサーバーです。このspecでは、LiteLLMの公式Dockerイメージ（ghcr.io/berriai/litellm:main-stable）を使用してコンテナをデプロイし、設定ファイルとセキュリティキーを適切に管理するAnsibleロールを作成します。

## Requirements

### Requirement 1

**User Story:** システム管理者として、LiteLLMコンテナを自動的にデプロイしたいので、手動でのコンテナ設定作業を削減し、一貫した環境を構築できる

#### Acceptance Criteria

1. WHEN Ansibleプレイブックを実行 THEN システムは公式のghcr.io/berriai/litellm:main-stableイメージを取得してコンテナを起動する
2. WHEN コンテナが起動 THEN LiteLLMプロキシサーバーがポート4000でリッスンしている
3. WHEN 設定ファイルが変更された THEN コンテナが自動的に再起動される
4. WHEN コンテナが起動 THEN 設定ファイル（config.yaml）がコンテナ内の/app/config.yamlにマウントされる
5. WHEN LiteLLMサービスが起動 THEN Apache proxyを使用せずに直接アクセスできる

### Requirement 2

**User Story:** 開発者として、AWS Bedrockを通じて最新のClaudeモデルにアクセスしたいので、推論プロファイルを使用して最新のClaudeモデルを利用できる

#### Acceptance Criteria

1. WHEN config.yamlにAWS Bedrockの推論プロファイルを定義 THEN LiteLLMが推論プロファイル経由でClaudeモデルをロードする
2. WHEN Claude 3.7 Sonnet, Claude Sonnet 4, Claude Opus 4を設定 THEN 推論プロファイル形式（us.anthropic.*）でアクセスできる
3. WHEN AWS認証情報を設定 THEN 環境変数からAWS認証情報が安全に読み込まれる
4. WHEN 推論プロファイルのリージョンを指定 THEN aws_region_nameが明示的に設定される

### Requirement 3

**User Story:** システム管理者として、LiteLLMの基本設定を管理したいので、標準的な設定でサービスを安定稼働できる

#### Acceptance Criteria

1. WHEN LiteLLMをデプロイ THEN ポート4000で固定的に起動する
2. WHEN 環境変数を設定 THEN AWS認証情報とLiteLLMキーがコンテナに渡される
3. WHEN 設定ファイルを生成 THEN 推論プロファイル形式のモデル設定が含まれる

### Requirement 4

**User Story:** システム管理者として、LiteLLMサービスの永続化を確保したいので、システム再起動後も自動的にサービスが開始される

#### Acceptance Criteria

1. WHEN システムが再起動される THEN LiteLLMコンテナが自動的に起動する
2. WHEN コンテナが異常終了 THEN Dockerの再起動ポリシーによって自動的に再起動される
3. WHEN サービスの状態を確認 THEN LiteLLMコンテナが正常に動作していることが確認できる

### Requirement 5

**User Story:** セキュリティ管理者として、LiteLLMのセキュリティ設定を管理したいので、不正アクセスを防止し、APIキーを安全に保護できる

#### Acceptance Criteria

1. WHEN LITELLM_MASTER_KEYが設定される THEN マスターキーがAnsible Vaultで暗号化される
2. WHEN LITELLM_SALT_KEYが設定される THEN ソルトキーがAnsible Vaultで暗号化される
3. WHEN AWS認証情報が設定される THEN AWS_ACCESS_KEY_IDとAWS_SECRET_ACCESS_KEYがAnsible Vaultで暗号化される
4. WHEN 設定ファイルが生成される THEN ファイル権限がroot:rootに設定される

### Requirement 6

**User Story:** 運用担当者として、LiteLLMの動作状況を確認したいので、基本的な監視とトラブルシューティングができる

#### Acceptance Criteria

1. WHEN コンテナ状態を確認 THEN `docker ps`でLiteLLMコンテナの状態が確認できる
2. WHEN ログを確認 THEN `docker logs litellm`でアプリケーションログが確認できる
3. WHEN AWS認証情報を確認 THEN `docker exec litellm env | grep AWS`で環境変数が確認できる
4. WHEN APIテストを実行 THEN curlコマンドでモデル一覧とチャット機能が確認できる
