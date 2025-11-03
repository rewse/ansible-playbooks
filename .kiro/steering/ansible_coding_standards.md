---
inclusion: fileMatch
fileMatchPattern: '*.yml'
---

# Ansible YAML 構文ガイドライン

## 基本構文

Ansible のプレイブックは YAML 形式で記述されます。YAML は人間が読みやすく、マシンでも解析しやすいデータシリアライゼーション形式です。

### インデント

- インデントには**スペース2つ**を使用する
- タブは使用しない
- ネストされた要素は親要素から2スペースインデントする

```yaml
---
# 良い例
- name: Update web servers
  hosts: webservers
  become: yes
  tasks:
    - name: Ensure Apache is installed
      ansible.builtin.apt:
        name: apache2
        state: present
```

### リスト

- リスト項目はハイフン（`-`）で始める
- ハイフンの後にはスペースを入れる

```yaml
# 良い例
fruits:
  - apple
  - orange
  - banana

# 悪い例
fruits:
-apple
-orange
-banana
```

### マッピング（キーと値のペア）

- キーと値の間にはコロン（`:`）とスペースを入れる

```yaml
# 良い例
name: John Smith
job: Developer
skills:
  - Python
  - Ansible
  - Docker

# 悪い例
name:John Smith
job:Developer
```

### 複数行の文字列

- 複数行の文字列には `|` または `>` を使用する
- `|` は改行を保持する
- `>` は改行をスペースに変換する

```yaml
# 改行を保持する場合
description: |
  This is a multi-line
  description that will
  preserve line breaks.

# 改行をスペースに変換する場合
description: >
  This is a multi-line
  description that will
  be folded into a single
  line with spaces.
```

### コメント

- コメントは `#` で始める
- `#` の後にはスペースを入れる

```yaml
# これはコメントです
name: Example  # これは行末コメントです
```

### 引用符

- 特殊文字を含む文字列はクォートで囲む
- 単純な文字列は引用符なしでも可能だが、一貫性のために引用符を使用することを推奨

```yaml
# 引用符が必要な場合
command: "echo 'Hello World'"
path: "/etc/ansible/hosts"

# 単純な文字列
state: present
```

### ブール値

- ブール値には `true`/`false` のみを使用する
- `yes`/`no` や `on`/`off` などの省略形は使用しない
- 小文字を使用する

```yaml
# 良い例
create_key: true
overwrite: false
ignore_errors: true
check_mode: false

# 悪い例
create_key: yes
overwrite: no
create_key: YES
overwrite: No
```

## Ansible 固有のガイドライン

### プレイブックの構造

- プレイブックは `---` で始める（オプションだが推奨）
- 各プレイは新しいリスト項目として定義する

```yaml
---
- name: First play
  hosts: webservers
  tasks:
    - name: First task
      ansible.builtin.debug:
        msg: "Hello World"

- name: Second play
  hosts: databases
  tasks:
    - name: First task
      ansible.builtin.debug:
        msg: "Hello Database"
```

### タスクの命名

- すべてのタスクに明確で説明的な名前を付ける
- 名前は動詞で始め、何をするのかを明確に示す

```yaml
# 良い例
- name: Install Apache web server
  ansible.builtin.apt:
    name: apache2
    state: present

# 悪い例
- name: Apache
  ansible.builtin.apt:
    name: apache2
    state: present
```

### 変数の使用

- 変数は二重中括弧で囲む
- 変数名とブレースの間にスペースを入れない

```yaml
# 良い例
- name: Create user {{ username }}
  ansible.builtin.user:
    name: "{{ username }}"
    state: present

# 悪い例
- name: Create user { { username } }
  ansible.builtin.user:
    name: { { username } }
    state: present
```

### モジュールパラメータ

- モジュールパラメータはインデントして整列させる
- 複数のパラメータがある場合は、各パラメータを新しい行に記述する

```yaml
# 良い例
- name: Copy configuration file
  ansible.builtin.copy:
    src: files/example.conf
    dest: /etc/example.conf
    owner: root
    group: root
    backup: true

# 悪い例
- name: Copy configuration file
  ansible.builtin.copy: src=files/example.conf dest=/etc/example.conf owner=root group=root mode=0644 backup=yes
```

### ファイルのパーミッション（mode）

- 特別な理由がない限り、ファイルの `mode` パラメータは設定しない
- 設定が必要な場合は、シングルクォートで囲んだ文字列として指定する
- 数値表記を使用する場合は、先頭に `0` を付けて8進数であることを明示する

```yaml
# 必要な場合の例
- name: Copy sensitive configuration file
  ansible.builtin.copy:
    src: files/secure.conf
    dest: /etc/secure.conf
    owner: root
    group: root
    mode: '0600'  # 特別なセキュリティ要件がある場合

# 通常は mode を省略
- name: Copy standard configuration file
  ansible.builtin.copy:
    src: files/standard.conf
    dest: /etc/standard.conf
    owner: root
    group: root
```

### ハンドラーの使用

- ハンドラー名は明確で一貫性のある命名規則に従う
- 通知するハンドラー名は正確に一致させる

```yaml
tasks:
  - name: Copy Apache configuration file
    ansible.builtin.copy:
      src: files/httpd.conf
      dest: /etc/httpd/conf/httpd.conf
    notify: Restart Apache

handlers:
  - name: Restart Apache
    ansible.builtin.service:
      name: httpd
      state: restarted
```

### タグの使用

- タグは配列形式で記述する
- 関連するタスクには一貫したタグを使用する

```yaml
# 良い例
- name: Install Apache
  ansible.builtin.apt:
    name: apache2
    state: present
  tags: [webserver, apache, installation]

# 悪い例
- name: Install Apache
  ansible.builtin.apt:
    name: apache2
    state: present
  tags: webserver, apache, installation
```

### 条件文

- 条件文は読みやすく整形する
- 複雑な条件は変数に格納することを検討する

```yaml
# 良い例
- name: Install Apache on Debian based systems
  ansible.builtin.apt:
    name: apache2
    state: present
  when: ansible_os_family == "Debian"

# 複雑な条件の場合
- name: Set complex condition
  ansible.builtin.set_fact:
    should_install: "{{ ansible_os_family == 'Debian' and ansible_distribution_version is version('18.04', '>=') }}"

- name: Install package with complex condition
  ansible.builtin.apt:
    name: some_package
    state: present
  when: should_install
```

### ループ

- ループには `loop` キーワードを使用する（`with_items` は非推奨）
- リスト項目は適切にインデントする

```yaml
# 良い例
- name: Install packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  loop:
    - apache2
    - mysql-server
    - php

# 悪い例
- name: Install packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  with_items: [apache2, mysql-server, php]
```

### デフォルト値の省略

- デフォルト値を持つパラメータは、値がデフォルトと同じ場合は記述しない
- 不要なパラメータを省略することで、YAMLをシンプルに保つ

```yaml
# 良い例
- name: Start service
  ansible.builtin.service:
    name: httpd
    state: started

# 悪い例（enabledのデフォルト値はno）
- name: Start service but don't enable
  ansible.builtin.service:
    name: httpd
    state: started
    enabled: false
```

```yaml
# 良い例
- name: Execute command
  ansible.builtin.command: /usr/bin/foo

# 悪い例（warnのデフォルト値はtrue）
- name: Execute command
  ansible.builtin.command: /usr/bin/foo
  args:
    warn: true
```

### シンプルな表記の優先

- 複雑な構造よりもシンプルな表記を優先する
- 読みやすさと保守性を向上させるために冗長な記述を避ける

```yaml
# 良い例
- name: Install multiple packages
  ansible.builtin.apt:
    name:
      - apache2
      - mysql-server
      - php
    state: present

# 悪い例（ループを使用した冗長な記述）
- name: Install multiple packages
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  loop:
    - apache2
    - mysql-server
    - php
```

### 完全修飾名（FQCN）の使用

Ansible 2.10以降、モジュールは完全修飾コレクション名（Fully Qualified Collection Name、FQCN）で参照することが推奨されています。これにより、モジュールの出所が明確になり、将来のバージョンでの互換性が向上します。

- 組み込みモジュールには `ansible.builtin.` プレフィックスを使用する
- コレクションモジュールには適切なコレクション名を使用する（例：`community.general.`）

```yaml
# 良い例（完全修飾名）
- name: Install Apache
  ansible.builtin.apt:
    name: apache2
    state: present

- name: Enable Apache module
  community.general.apache2_module:
    name: rewrite
    state: present

# 悪い例（短縮形）
- name: Install Apache
  apt:
    name: apache2
    state: present

- name: Copy file
  copy:
    src: file.txt
    dest: /tmp/file.txt
```

#### 主要な組み込みモジュールのFQCN

| 短縮形 | 完全修飾名 (FQCN) |
|--------|-------------------|
| `apt` | `ansible.builtin.apt` |
| `copy` | `ansible.builtin.copy` |
| `file` | `ansible.builtin.file` |
| `template` | `ansible.builtin.template` |
| `service` | `ansible.builtin.service` |
| `shell` | `ansible.builtin.shell` |
| `command` | `ansible.builtin.command` |
| `debug` | `ansible.builtin.debug` |
| `set_fact` | `ansible.builtin.set_fact` |
| `include_vars` | `ansible.builtin.include_vars` |
| `include_tasks` | `ansible.builtin.include_tasks` |

#### 移行戦略

既存のプロジェクトを完全修飾名に移行する場合は、以下の戦略を検討してください：

1. 新しいタスクやロールでは常に完全修飾名を使用する
2. 既存のコードを修正する際には、そのファイル内のモジュール名を完全修飾名に更新する
3. 一貫性を保つために、ファイル単位で更新を行う

## ベストプラクティス

1. **一貫性を保つ**: プロジェクト全体で一貫したスタイルを使用する
2. **モジュール名を完全に記述する**: 完全修飾名（FQCN）を使用する
3. **適切なインデント**: 読みやすさを向上させるために適切なインデントを使用する
4. **説明的な名前**: タスク、プレイ、ロールに説明的な名前を付ける
5. **コメントを追加する**: 複雑なタスクや条件にはコメントを追加する
6. **変数の使用**: ハードコードされた値の代わりに変数を使用する
7. **タグを効果的に使用する**: 選択的な実行のためにタグを使用する
8. **ファイルを分割する**: 大きなプレイブックは小さなファイルに分割する
9. **デフォルト値を省略する**: デフォルト値と同じ設定は記述しない
10. **シンプルな表記を優先する**: 可能な限り簡潔で読みやすい構文を使用する

## Vault コマンド

### Vault ファイルの操作

```bash
# Vault ファイルを編集
ansible-vault edit group_vars/all/vault

# 新しい Vault ファイルを作成
ansible-vault create new_vault_file.yml

# 既存のファイルを暗号化
ansible-vault encrypt plain_file.yml

# Vault ファイルの内容を確認
ansible-vault view group_vars/all/vault | cat
```

## 参考資料

- [Ansible YAML Syntax](https://docs.ansible.com/ansible/latest/reference_appendices/YAMLSyntax.html)
- [Ansible Best Practices](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html)
