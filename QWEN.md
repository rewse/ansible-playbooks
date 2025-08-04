# Ansible インフラストラクチャ管理リポジトリ - 統合ガイドライン

このドキュメントは、すべてのsteeringファイルの内容を統合したものです。

## プロジェクト概要

このリポジトリには、様々な環境にわたるインフラストラクチャコンポーネントを管理するための Ansible プレイブックとロールが含まれています。対象となるインフラストラクチャには以下が含まれます：

- Ubuntu サーバー
- AWS の EC2 インスタンス
- Raspberry Pi デバイス
- macOS マシン（ビジネス用と個人用）

このオートメーションは以下のような幅広いサービスとアプリケーションをカバーしています：

- Home Assistant によるホームオートメーション
- Web サーバー（Apache, Nginx）
- データベースシステム（CouchDB）
- 監視ソリューション（Zabbix）
- IoT デバイスと統合（SwitchBot, Matter, MQTT）
- 開発環境
- セキュリティ設定と SSL 証明書
- Docker 環境
- クラウドサービス統合

このリポジトリは、複数のホストとプラットフォームにわたって一貫した環境を維持するための中央構成管理システムとして機能します。

## 技術スタック

### コア技術
- **Ansible**: 構成管理のための主要な自動化ツール
- **YAML**: プレイブック、ロール、変数定義に使用
- **Jinja2**: 動的構成ファイルのためのテンプレートエンジン
- **Vault**: 機密情報の安全な保存のため

### プラットフォーム
- **Ubuntu**: Linux サーバーとクラウドインスタンス
- **AWS EC2**: クラウドインフラストラクチャ
- **Raspberry Pi**: IoT とホームオートメーションデバイス
- **macOS**: 開発者ワークステーション（ビジネス用と個人用）

### サービスとアプリケーション
- **Web サーバー**: Apache HTTPD
- **データベース**: CouchDB
- **監視**: Zabbix
- **ホームオートメーション**: Home Assistant, MQTT (Mosquitto), Matter
- **IoT**: SwitchBot, MHZ19 センサー, Enecoq
- **クラウドサービス**: AWS 統合
- **セキュリティ**: certbot による SSL 証明書, SSH 設定

## プロジェクト構造

### トップレベルの構成
- **プレイブック**: ルートレベルの YAML ファイル（例：`site.yml`, `ubuntu.yml`, `ec2.yml`）
- **インベントリ**: `hosts` ファイルのホスト定義
- **設定**: `ansible.cfg` の Ansible 設定
- **グループ変数**: `group_vars/` ディレクトリに保存
- **ロール**: `roles/` ディレクトリのモジュラーコンポーネント

### プレイブック構造
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

### ロール構造
各ロールは標準的な Ansible ディレクトリ構造に従います：
- `tasks/`: ロールのタスクを含む main.yml
- `handlers/`: タスクによってトリガーされるイベントハンドラー
- `templates/`: Jinja2 テンプレート（*.j2）
- `files/`: ホストにコピーする静的ファイル
- `vars/`: ロール固有の変数
- `meta/`: ロールの依存関係とメタデータ

### 変数の階層
1. **グループ変数**: `group_vars/group_name/vars`
2. **Vault 変数**: `group_vars/group_name/vault`
3. **ロール変数**: `roles/role_name/vars/main.yml`
4. **ホスト変数**: インベントリまたは別のファイルで定義

### 命名規則
- **ファイル**: アンダースコアまたはハイフン付きの小文字を使用
- **変数**: スネークケース（アンダースコア付きの小文字）を使用
- **ロール**: その目的を反映した説明的な名前を使用
- **タグ**: ロール名をプレフィックスとしてカテゴリを続ける（例：`ubuntu,package`）
- **タグのフォーマット**: タグは配列形式で記述する（例：`tags: [ubuntu, package]`）

### ベストプラクティス
- 関連するロールをサブディレクトリに整理する（例：`zabbix/agent/ubuntu`）
- 選択的な実行のためにタグを一貫して使用する
- タグは常に配列形式で記述する（例：`tags: [ubuntu, package]`）
- ロールは単一の責任に焦点を当てる
- サービスの再起動やその他のトリガーされるアクションにはハンドラーを活用する
- 動的構成ファイルにはテンプレートを使用する
- 機密データは Vault ファイルに保存する

## 言語使用ガイドライン

### 基本方針
このプロジェクトでは、以下の言語使用ポリシーに従ってください：

- **コード内のコメント**: 英語
- **チャットでのコミュニケーション**: 日本語
- **仕様書（Spec）**: 日本語
- **ドキュメント**: 日本語
- **コミットメッセージ**: 英語
- **変数名・関数名**: 英語

### 詳細ガイドライン

#### コード内コメント（英語）
コード内のコメントは、国際的な開発環境との互換性を保つため、すべて英語で記述してください。

例：
```yaml
# Set timezone for the server
- name: Set timezone
  timezone:
    name: Asia/Tokyo
  tags: [ubuntu, time]
```

#### チャットコミュニケーション（日本語）
Kiroとのチャットやコミュニケーションは日本語で行ってください。技術的な質問、回答、説明などはすべて日本語で提供されます。

##### 口調について
チャットでのコミュニケーションは親しみやすい口調を使用してください：
- 語尾は「するね」「したよ」のような親しみやすい口調にする
- 丁寧語を基本とするが、親しみやすさを重視する
- 技術的な内容でも分かりやすく説明する
- 適度にカジュアルで親近感のある表現を使う
- 感嘆詞（！）はなるべく使わない。感情が高まったときだけにとどめる
- ちいかわのハチワレの口癖をたまに混ぜる
  - ○○ってこと？ / ○○ってコト!?（状況を確認・説明するとき）
  - 泣いちゃった！（誰かが困っている様子を見て）
  - なんとかなれ！（困難に対して対処する様子）
  - エーヘヘ（照れている様子）
  - キャハハ（笑っている様子）
  - なになに（何かに興味を持っている様子）
  - サイコーじゃない？（最高なことに喜んでいる様子）
  - こんなんさァッッ絶対アレじゃん（明らかな状況に対して）
  - 心がふたつある～（二択で迷うとき）
  - すぐにしたかったんだッ…「共有」ッ（何かを伝えたいとき）
  - なっちゃったの!!? ○○!!!（倒置法的な驚きの表現）
  - なんか…してきたねーッワクワク!!（期待感を表すとき）

#### 仕様書（日本語）
プロジェクトの仕様書、要件定義、設計ドキュメントなどは日本語で作成してください。

#### コミットメッセージ（英語）
Gitのコミットメッセージは、一般的な慣習に従って英語で記述してください。

#### 変数名・関数名（英語）
コード内の変数名、関数名、ロール名などは、標準的な開発慣習に従って英語で命名してください。

### 翻訳ポリシー
- 技術用語は基本的に英語のままとし、必要に応じて日本語の説明を付記する
- 英語のドキュメントを参照する場合は、元の英語と日本語訳の両方を提供する
- 専門用語の訳語は一貫性を保つ

## Ansible YAML 構文ガイドライン

### 基本構文

Ansible のプレイブックは YAML 形式で記述されます。YAML は人間が読みやすく、マシンでも解析しやすいデータシリアライゼーション形式です。

#### インデント

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

#### リスト

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

#### マッピング（キーと値のペア）

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

#### 複数行の文字列

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

#### コメント

- コメントは `#` で始める
- `#` の後にはスペースを入れる

```yaml
# これはコメントです
name: Example  # これは行末コメントです
```

#### 引用符

- 特殊文字を含む文字列はクォートで囲む
- 単純な文字列は引用符なしでも可能だが、一貫性のために引用符を使用することを推奨

```yaml
# 引用符が必要な場合
command: "echo 'Hello World'"
path: "/etc/ansible/hosts"

# 単純な文字列
state: present
```

#### ブール値

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

### Ansible 固有のガイドライン

#### プレイブックの構造

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

#### タスクの命名

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

#### 変数の使用

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

#### モジュールパラメータ

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

#### ファイルのパーミッション（mode）

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

#### ハンドラーの使用

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

#### タグの使用

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

#### 条件文

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

#### ループ

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

#### デフォルト値の省略

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

#### シンプルな表記の優先

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

#### 完全修飾名（FQCN）の使用

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

##### 主要な組み込みモジュールのFQCN

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

### ベストプラクティス

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

## Home Assistant 開発ガイドライン

### YAML スタイルガイド

Home Assistant の公式 YAML スタイルガイド（[developers.home-assistant.io/docs/documenting/yaml-style-guide/](https://developers.home-assistant.io/docs/documenting/yaml-style-guide/)）に基づいたガイドラインです。

#### インデント

- インデントには**スペース2つ**を使用する
- タブは使用しない
- ネストされた要素は親要素から2スペースインデントする

```yaml
# 良い例
automation:
  - alias: Good example
    trigger:
      - platform: state
        entity_id: binary_sensor.motion
```

#### 真偽値

- 真偽値は `true` と `false` を使用する（小文字）
- `yes`/`no` や `on`/`off` などの省略形は使用しない（YAML 1.2仕様との互換性のため）

```yaml
# 良い例
one: true
two: false

# 悪い例
one: True
two: on
three: yes
```

#### コメント

- コメントはインデントレベルに合わせる
- コメントは対象行の上に書くことが望ましい
- コメントは大文字で始め、`#` とコメントの間にスペースを入れる

```yaml
# 良い例
example:
  # コメント
  one: true

# 許容可能だが上記が望ましい
example:
  one: true # コメント
```

#### シーケンス（リスト）

- ブロックスタイルのシーケンスを優先する
- フロースタイル（`[1, 2, 3]`）は可能な限り避ける

##### ブロックスタイルシーケンス

```yaml
# 良い例
example:
  - 1
  - 2
  - 3

# 悪い例
example:
- 1
- 2
- 3
```

##### フロースタイルシーケンス

使用する場合は、カンマの後にスペースを入れ、開始・終了括弧の前後にスペースを入れない：

```yaml
# 良い例
example: [1, 2, 3]

# 悪い例
example: [ 1,2,3 ]
example: [ 1, 2, 3 ]
```

#### マッピング

- マッピングはブロックスタイルのみを使用する
- フロースタイル（JSON風の記法）は使用しない

```yaml
# 良い例
example:
  one: 1
  two: 2

# 悪い例
example: { one: 1, two: 2 }
```

#### Null値

- Null値は暗黙的に表現する
- 明示的なNull値（`~` や `null`）は避ける

```yaml
# 良い例
example:

# 悪い例
example: ~
example: null
```

#### 文字列

- 文字列は**ダブルクォート**（`"`）で囲むことが望ましい

```yaml
# 良い例
example: "Hi there!"

# 避けるべき例
example: Hi there!

# 悪い例
example: 'Hi there!'
```

### テンプレート記法

#### 関数とフィルターの使用

Home Assistantのテンプレートでは、フィルターよりも関数を優先して使用してください。関数はより明示的で、コードの可読性と保守性が向上します。

##### 推奨される方法（関数を使用）

```yaml
# 整数変換に関数を使用
state: "{{ int(state_attr('sensor.example', 'value')) }}"

# 浮動小数点変換に関数を使用
state: "{{ float(states('sensor.temperature')) }}"

# 文字列置換に関数を使用
state: "{{ state_attr('sensor.example', 'text') | replace('%', '') }}"
```

##### 避けるべき方法（フィルターのみを使用）

```yaml
# 整数変換にフィルターを使用（避ける）
state: "{{ state_attr('sensor.example', 'value') | int }}"

# 浮動小数点変換にフィルターを使用（避ける）
state: "{{ states('sensor.temperature') | float }}"
```

#### テンプレート構造

- 100文字を超えるテンプレートには複数行形式（`>-`）を使用する
- 100文字を超えないテンプレートには一行形式（`"{{ ... }}"`）を使用する
- テンプレート内の条件文は適切にインデントする

#### センサー定義

- すべてのセンサーに `unique_id` を設定する
- 適切な `device_class` と `state_class` を設定する
- 測定値には適切な `unit_of_measurement` を設定する

### ベストプラクティス

1. **明示的な型変換**: 値を操作する前に、明示的に型変換を行う（例: `int()`, `float()`）
2. **エラーハンドリング**: 値が存在しない場合のデフォルト値を設定する
3. **コメント**: 複雑なテンプレートにはコメントを追加する
4. **命名規則**: センサー名は一貫した命名規則に従う
5. **再利用**: 共通のテンプレートは再利用可能な形で設計する

### 例

#### 良い例

```yaml
- template:
  - sensor:
      - unique_id: sensor.outside_temperature
        name: "Outside Temperature"
        state: "{{ float(states('sensor.weather_temperature')) }}"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
```

#### 避けるべき例

```yaml
- platform: template
  sensors:
    outside_temperature:
      friendly_name: "Outside Temperature"
      value_template: "{{ states('sensor.weather_temperature') | float(0) }}"
      unit_of_measurement: "°C"
```

### ファイル構成

#### コンポーネント別のファイル分割

- 関連するコンポーネントごとにファイルを分割する
- 論理的なグループごとにファイルを整理する
- 大きなファイルは小さな管理しやすいファイルに分割する

```
homeassistant/
  sensors.yaml      # センサー定義
  templates.yaml    # テンプレートセンサー
  automations.yaml  # 自動化
  scripts.yaml      # スクリプト
  scenes.yaml       # シーン
```

これらのファイルは `configuration.yaml` から以下のように読み込まれている。

```
sensor: !include sensors.yaml
shell_command: !include shell_commands.yaml
switch: !include switches.yaml
template: !include templates.yaml
```

そのため、分割されたファイルは先頭のkeyを省略する必要がある。

##### 良い例

```
- platform: statistics
  unique_id: sensor.balcony_humidity_difference_average
  name: "Balcony Humidity Difference Average"
  entity_id: sensor.balcony_humidity_difference
  state_characteristic: mean
  max_age:
    hours: 51
- platform: statistics
  unique_id: sensor.balcony_temp_average
  name: "Balcony Temperature Average"
  entity_id: sensor.balcony_temperature
  state_characteristic: mean
  max_age:
    hours: 24
```

##### 悪い例

```
sensor:
  - platform: statistics
    unique_id: sensor.balcony_humidity_difference_average
    name: "Balcony Humidity Difference Average"
    entity_id: sensor.balcony_humidity_difference
    state_characteristic: mean
    max_age:
      hours: 51
  - platform: statistics
    unique_id: sensor.balcony_temp_average
    name: "Balcony Temperature Average"
    entity_id: sensor.balcony_temperature
    state_characteristic: mean
    max_age:
      hours: 24
```

#### コメント

- セクションの開始時にはコメントを使用して内容を説明する
- 複雑な設定には説明コメントを追加する
- コメントは `#` の後にスペースを入れる

```yaml
# Balcony sensors
- platform: template
  sensors:
    balcony_temperature:
      friendly_name: "Balcony Temperature"
      # Average of two temperature sensors for better accuracy
      value_template: >-
        {{ (float(states('sensor.balcony_temp_1')) + 
            float(states('sensor.balcony_temp_2'))) / 2 }}
```

#### 命名規則

- エンティティIDはスネークケース（小文字とアンダースコア）を使用する
- 関連するエンティティには一貫したプレフィックスを使用する
- 名前は具体的で説明的にする

```yaml
# 良い例
sensor:
  - platform: template
    sensors:
      living_room_temperature:
        friendly_name: "Living Room Temperature"
      living_room_humidity:
        friendly_name: "Living Room Humidity"
```

### 設定のベストプラクティス

#### 再利用可能な設定

- 共通の設定は再利用可能な形で設計する
- パッケージ機能を活用して関連する設定をグループ化する

#### バージョン管理

- 設定ファイルはバージョン管理システム（Git など）で管理する
- 変更履歴を追跡し、問題が発生した場合に以前の状態に戻せるようにする

#### テスト

- 設定変更後は Home Assistant の設定チェック機能を使用して検証する
- 大きな変更を行う前にバックアップを作成する

#### セキュリティ

- 機密情報（パスワード、トークン、APIキーなど）は `!secret` を使用して保護する
- 公開リポジトリに機密情報を含めない

```yaml
# 良い例
http:
  api_password: !secret http_password
```

## コミットメッセージガイドライン

このプロジェクトでは、コミットメッセージは [Conventional Commits 1.0.0](https://www.conventionalcommits.org/ja/v1.0.0/) の仕様に従って記述してください。

### 基本構造

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### タイプ (type)

コミットのタイプは以下のいずれかを使用してください：

- **feat**: 新機能
- **fix**: バグ修正
- **docs**: ドキュメントのみの変更
- **style**: コードの意味に影響を与えない変更（空白、フォーマット、セミコロンの欠落など）
- **refactor**: バグ修正でも機能追加でもないコードの変更
- **perf**: パフォーマンスを向上させるコード変更
- **test**: 不足しているテストの追加または既存のテストの修正
- **build**: ビルドシステムまたは外部依存関係に影響する変更（例：ansible, pip, docker）
- **ci**: CI設定ファイルとスクリプトの変更
- **chore**: その他の変更（上記のどれにも当てはまらないもの）

### スコープ (scope)

スコープはコミットの変更が影響する範囲を示します。特定のロールに関わる変更の場合は、**スコープ名にはロール名を使用してください**。

例：
- `feat(ubuntu): add new package installation task`
- `fix(zabbix): correct agent configuration template`
- `docs(homeassistant): update setup instructions`

### 説明 (description)

説明は短く、変更内容を簡潔に表現してください。英語で記述し、命令形の現在形を使用します。最初の文字は小文字にし、末尾にピリオドを付けないでください。

### 本文 (body)

本文は任意で、変更の動機や以前の動作との対比など、より詳細な説明を提供します。段落として書式設定する必要があります。

### フッター (footer)

フッターは任意で、Breaking Changes に関する情報や、解決された Issue への参照を含めることができます。

#### Breaking Changes

Breaking Changes がある場合は、フッターに `BREAKING CHANGE:` というテキストを含め、その後に説明を続けます。または、タイプ/スコープの後に `!` を追加して示すこともできます。

例：
```
feat(homeassistant)!: change configuration format

BREAKING CHANGE: The configuration format has been changed to support new features.
```

#### Issue の参照

解決された Issue への参照を含める場合は、以下のように記述します：

```
fix(mosquitto): correct connection timeout

Closes #123
```

### 例

#### 新機能の追加
```
feat(ubuntu): add ghostty terminal support
```

#### バグ修正
```
fix(docker): resolve container startup issue
```

#### ドキュメント更新
```
docs: update README with new installation instructions
```

#### 複数のロールに影響する変更
```
refactor: standardize task naming across roles
```

#### Breaking Change を含む変更
```
feat(zabbix)!: upgrade to version 6.0

BREAKING CHANGE: This version requires new database schema.
```

### 注意事項

- コミットメッセージは英語で記述してください
- 1つのコミットでは1つの論理的な変更のみを行ってください
- コミットメッセージは明確で理解しやすいものにしてください
- 長い説明が必要な場合は、本文に詳細を記述してください

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

# Vault ファイルの内容を確認
ansible-vault view group_vars/all/vault | cat
```

### 便利なGitコマンド

#### 出力表示の確実性を高めるためのパイプ

以下のGitコマンドは、出力が表示されない場合があります。確実に標準出力に結果を表示するために、`cat` コマンドにパイプすることをお勧めします：

##### ステージングされた変更の確認

```bash
git diff --staged | cat
```

##### コミット内容の表示

```bash
git show | cat
git show HEAD | cat
git show <commit-hash> | cat
```

##### コミット履歴の表示

```bash
git log | cat
git log -p | cat
git log --stat | cat
git log --oneline | cat
```

##### ブランチ間の差分

```bash
git diff branch1..branch2 | cat
```

##### ファイルの変更履歴

```bash
git blame <file> | cat
```

これらのコマンドに `cat` をパイプすることで、ページャー（less/more）を経由せずに直接標準出力に結果が表示され、出力が確実に見えるようになります。特にスクリプトやエイリアス内でGitコマンドを使用する場合に有用です。

### ベストプラクティス
- 選択的な実行にはタグを常に使用する
- 機密データは Vault ファイルに保管する
- 共有設定には group_vars を使用する
- 変更を適用する前に --check で確認する
- ロール固有の変数は role/vars ディレクトリに保持する

## 参考資料

- [Ansible YAML Syntax](https://docs.ansible.com/ansible/latest/reference_appendices/YAMLSyntax.html)
- [Ansible Best Practices](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html)
- [Home Assistant YAML Style Guide](https://developers.home-assistant.io/docs/documenting/yaml-style-guide/)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/ja/v1.0.0/)
