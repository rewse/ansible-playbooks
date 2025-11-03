---
inclusion: always
---

# プロジェクト構造

## トップレベルの構成
- **プレイブック**: ルートレベルの YAML ファイル（例：`site.yml`, `ubuntu.yml`, `ec2.yml`）
- **インベントリ**: `hosts` ファイルのホスト定義
- **設定**: `ansible.cfg` の Ansible 設定
- **グループ変数**: `group_vars/` ディレクトリに保存
- **ロール**: `roles/` ディレクトリのモジュラーコンポーネント

## プレイブック構造
プレイブックは一貫したパターンに従います：
- ターゲットホストの定義
- 共通パラメータの設定（become, remote_user）
- 関連するロールの適用

例：
```yaml
---
- hosts: ubuntu
  become: yes
  remote_user: ubuntu
  tags: [ubuntu]
  roles:
    - ubuntu
    - postfix/client
    - dotfiles/linux
```

タスク例：
```yaml
- name: Install required packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  loop: "{{ required_packages }}"
  tags: [ubuntu, package]
```

## ロール構造
各ロールは標準的な Ansible ディレクトリ構造に従います：
- `tasks/`: ロールのタスクを含む main.yml
- `handlers/`: タスクによってトリガーされるイベントハンドラー
- `templates/`: Jinja2 テンプレート（*.j2）
- `files/`: ホストにコピーする静的ファイル
- `vars/`: ロール固有の変数
- `meta/`: ロールの依存関係とメタデータ

## 変数の階層
1. **グループ変数**: `group_vars/group_name/vars`
2. **Vault 変数**: `group_vars/group_name/vault`
3. **ロール変数**: `roles/role_name/vars/main.yml`
4. **ホスト変数**: インベントリまたは別のファイルで定義

## 命名規則
- **ファイル**: アンダースコアまたはハイフン付きの小文字を使用
- **変数**: スネークケース（アンダースコア付きの小文字）を使用
- **ロール**: その目的を反映した説明的な名前を使用
- **タグ**: ロール名をプレフィックスとしてカテゴリを続ける（例：`ubuntu,package`）
- **タグのフォーマット**: タグは配列形式で記述する（例：`tags: [ubuntu, package]`）

## ベストプラクティス
- 関連するロールをサブディレクトリに整理する（例：`zabbix/agent/ubuntu`）
- 選択的な実行のためにタグを一貫して使用する
- タグは常に配列形式で記述する（例：`tags: [ubuntu, package]`）
- ロールは単一の責任に焦点を当てる
- サービスの再起動やその他のトリガーされるアクションにはハンドラーを活用する
- 動的構成ファイルにはテンプレートを使用する
- 機密データは Vault ファイルに保存する
