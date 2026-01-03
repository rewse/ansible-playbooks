# 設計ドキュメント

## 概要

このドキュメントでは、MCPサーバーの設定ファイルをAnsibleを使用して配置するための設計を定義します。この設計は、macOSシステムにMCPサーバー設定ファイルを効率的に配置し、Kiro、Amazon Q Developer、akiなどの複数のMCPサーバー対応ツールから共通して参照できるようにすることを目的としています。また、MCPサーバーの実行に必要な一般的なコマンドやツール（uvx、uv、Pythonなど）のインストールも含みます。

## アーキテクチャ

この機能は、Ansibleのロールとして実装され、既存のAnsibleインフラストラクチャに統合されます。主要なコンポーネントは以下の通りです：

1. **MCPサーバー設定ロール**: `roles/mcp-server` ディレクトリに配置される新しいAnsibleロール
2. **設定テンプレート**: Jinja2テンプレートを使用して、環境変数に基づいて動的に生成される設定ファイル
3. **変数定義**: 環境ごとに異なる設定値を定義するための変数ファイル
4. **タスク定義**: 設定ファイルの配置と検証を行うためのAnsibleタスク
5. **パッケージインストール**: MCPサーバーの実行に必要なコマンド（uvx、uv）をインストールするためのタスク
6. **環境分け**: `mcp-server-personal`と`mcp-server-business`のタグを使用して、個人用と業務用の環境を分ける

アーキテクチャの概略図：

```
ansible-infrastructure/
├── roles/
│   └── mcp-server/
│       ├── tasks/
│       │   ├── main.yml       # メインタスク定義
│       │   └── install.yml    # パッケージインストールタスク
│       ├── templates/
│       │   └── mcp.json.j2    # 設定ファイルのテンプレート
│       ├── handlers/
│       │   └── main.yml       # ハンドラー定義
│       └── vars/
│           ├── main.yml       # 共通のデフォルト変数
│           ├── personal.yml   # 個人環境用の変数
│           └── business.yml   # 業務環境用の変数
└── darwin-*.yml               # macOS用プレイブック
```

## コンポーネントとインターフェース

### 1. タスク定義 (tasks/main.yml)

メインタスク定義ファイルには、以下の主要なタスクが含まれます：

1. 必要なパッケージのインストールタスクのインクルード
2. 設定ディレクトリの作成
3. 設定ファイルのテンプレート配置
4. 設定ファイルの検証
5. 必要に応じたシンボリックリンクの作成

```yaml
# タスク定義の概略
- name: Include package installation tasks
  include_tasks: install.yml
  tags: [mcp-server, mcp-server-personal, mcp-server-business, install]

- name: Ensure config directory exists
  file:
    path: "{{ mcp_config_dir }}"
    state: directory
  tags: [mcp-server, mcp-server-personal, mcp-server-business, config]

- name: Deploy MCP server configuration
  template:
    src: mcp.json.j2
    dest: "{{ mcp_config_file }}"
    mode: '0600'
  register: config_deployment
  tags: [mcp-server, mcp-server-personal, mcp-server-business, config]

- name: Validate MCP configuration
  command: python -m json.tool "{{ mcp_config_file }}"
  changed_when: false
  when: config_deployment.changed
  tags: [mcp-server, mcp-server-personal, mcp-server-business, config, validate]
```

### 2. パッケージインストールタスク (tasks/install.yml)

パッケージインストールタスクファイルには、MCPサーバーの実行に必要なコマンドをインストールするタスクが含まれます：

```yaml
# パッケージインストールタスクの概略
- name: Install uv package manager
  pip:
    name: uv
    state: present
  tags: [mcp-server, mcp-server-personal, mcp-server-business, install, uv]

- name: Ensure uvx is available
  command: uv --version
  register: uv_version
  changed_when: false
  failed_when: false
  tags: [mcp-server, mcp-server-personal, mcp-server-business, install, check]

- name: Install uvx if not available
  pip:
    name: uvx
    state: present
  when: uv_version.rc != 0
  tags: [mcp-server, mcp-server-personal, mcp-server-business, install, uvx]
```

### 3. 設定テンプレート (templates/mcp.json.j2)

設定テンプレートは、Jinja2形式で記述され、変数から動的に設定ファイルを生成します：

```jinja
{
  "mcpServers": {
{% for server_name, server_config in mcp_servers.items() %}
    "{{ server_name }}": {
      "command": "{{ server_config.command }}",
      "args": {{ server_config.args | to_json }},
{% if server_config.env is defined %}
      "env": {{ server_config.env | to_json }},
{% endif %}
      "disabled": {{ server_config.disabled | default(false) | lower }},
      "autoApprove": {{ server_config.autoApprove | default([]) | to_json }}
    }{% if not loop.last %},{% endif %}
{% endfor %}
  }
}
```

### 4. 変数定義 (vars/main.yml)

デフォルト変数を定義し、環境固有の変数でオーバーライドできるようにします：

```yaml
# デフォルト変数
mcp_config_dir: "{{ ansible_facts['env']['HOME'] }}/.config"
mcp_config_file: "{{ mcp_config_dir }}/mcp.json"

# デフォルトのMCPサーバー設定
mcp_servers:
  aws-docs:
    command: "uvx"
    args: ["awslabs.aws-documentation-mcp-server@latest"]
    env:
      FASTMCP_LOG_LEVEL: "ERROR"
    disabled: false
    autoApprove: []
```

## データモデル

### 設定ファイル構造

MCPサーバー設定ファイル（mcp.json）は以下の構造を持ちます：

```json
{
  "mcpServers": {
    "server-name": {
      "command": "command-to-run",
      "args": ["arg1", "arg2"],
      "env": {
        "ENV_VAR1": "value1",
        "ENV_VAR2": "value2"
      },
      "disabled": false,
      "autoApprove": ["tool1", "tool2"]
    },
    "another-server": {
      // 別のサーバー設定
    }
  }
}
```

### 変数モデル

Ansible変数は以下の構造で定義されます：

```yaml
# 基本設定
mcp_config_dir: "パス/to/config/ディレクトリ"
mcp_config_file: "パス/to/config/ファイル"

# サーバー設定
mcp_servers:
  サーバー名:
    command: "実行コマンド"
    args: ["引数1", "引数2"]
    env:  # オプション
      ENV_VAR1: "値1"
      ENV_VAR2: "値2"
    disabled: true|false  # オプション、デフォルトはfalse
    autoApprove: ["ツール1", "ツール2"]  # オプション、デフォルトは空リスト
```

### 環境別の変数定義

個人用と業務用の環境で異なる設定を適用するために、以下のように変数を定義します：

1. **共通設定**: `roles/mcp-server/vars/main.yml` に共通の設定を定義
2. **個人用設定**: `roles/mcp-server/vars/personal.yml` に個人用の設定を定義
3. **業務用設定**: `roles/mcp-server/vars/business.yml` に業務用の設定を定義

プレイブック実行時に適切なタグ（`mcp-server-personal`または`mcp-server-business`）を指定することで、対応する環境の設定が適用されます。

## エラー処理

1. **設定ディレクトリ作成エラー**:
   - ディレクトリ作成に失敗した場合、適切なエラーメッセージを表示し、タスクを中止します。
   - 権限の問題が発生した場合、必要な権限を取得するための指示を提供します。

2. **設定ファイル検証エラー**:
   - JSON構文が無効な場合、エラーメッセージを表示し、タスクを中止します。
   - 検証エラーの詳細を表示して、問題の特定と修正を容易にします。

3. **シンボリックリンク作成エラー**:
   - リンク作成に失敗した場合、警告を表示しますが、タスク全体は中止しません。
   - 既存のリンクや競合するファイルがある場合、適切に処理します。

## テスト戦略

1. **単体テスト**:
   - 設定テンプレートが有効なJSONを生成することを確認
   - 変数の置換が正しく行われることを確認
   - パッケージインストールタスクが正しく動作することを確認

2. **統合テスト**:
   - Ansibleプレイブックが正常に実行されることを確認
   - 設定ファイルが正しい場所に配置されることを確認
   - 設定ファイルの内容が期待通りであることを確認
   - 必要なコマンド（uvx、uv）が正しくインストールされることを確認

3. **検証テスト**:
   - 生成された設定ファイルが実際のMCPサーバー対応ツールで正常に読み込まれることを確認
   - 異なる環境設定で正しく動作することを確認
   - インストールされたコマンドがMCPサーバーを正常に実行できることを確認

## 実装の考慮事項

1. **互換性**:
   - 既存のAnsibleインフラストラクチャとの互換性を確保
   - 異なるmacOSバージョンでの動作を確認

2. **柔軟性**:
   - 環境ごとに異なる設定を容易に定義できるようにする
   - 将来的なMCPサーバーの追加や変更に対応できる設計

3. **メンテナンス性**:
   - コードの可読性と保守性を確保
   - 適切なコメントとドキュメントを提供

4. **セキュリティ**:
   - 機密情報の適切な処理
   - 適切なファイル権限の設定
