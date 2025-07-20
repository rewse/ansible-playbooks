# MCP Server Configuration

このディレクトリには、MCPサーバーの設定ファイルのテンプレートが含まれています。

## テンプレート

- `mcp.json.j2`: MCPサーバーの設定ファイルのテンプレート

## 変数

テンプレートは以下の変数を使用します：

- `mcp_config_dir`: 設定ディレクトリのパス（デフォルト: `{{ ansible_env.HOME }}/.config`）
- `mcp_config_file`: 設定ファイルのパス（デフォルト: `{{ mcp_config_dir }}/mcp.json`）
- `mcp_servers`: MCPサーバーの設定を含む辞書
  - 各サーバーは以下の構造を持ちます：
    ```yaml
    サーバー名:
      command: "実行コマンド"
      args: ["引数1", "引数2"]
      env:  # オプション
        ENV_VAR1: "値1"
        ENV_VAR2: "値2"
      workingDir: "作業ディレクトリ"  # オプション
      disabled: true|false  # オプション、デフォルトはfalse
      autoApprove: ["ツール1", "ツール2"]  # オプション、デフォルトは空リスト
    ```
- `mcp_additional_config`: 追加の設定（オプション）
