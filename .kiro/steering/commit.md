# コミットメッセージガイドライン

このプロジェクトでは、コミットメッセージは [Conventional Commits 1.0.0](https://www.conventionalcommits.org/ja/v1.0.0/) の仕様に従って記述してください。

## 基本構造

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

## タイプ (type)

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

## スコープ (scope)

スコープはコミットの変更が影響する範囲を示します。特定のロールに関わる変更の場合は、**スコープ名にはロール名を使用してください**。

例：
- `feat(ubuntu): add new package installation task`
- `fix(zabbix): correct agent configuration template`
- `docs(homeassistant): update setup instructions`

## 説明 (description)

説明は短く、変更内容を簡潔に表現してください。英語で記述し、命令形の現在形を使用します。最初の文字は小文字にし、末尾にピリオドを付けないでください。

## 本文 (body)

本文は任意で、変更の動機や以前の動作との対比など、より詳細な説明を提供します。段落として書式設定する必要があります。

## フッター (footer)

フッターは任意で、Breaking Changes に関する情報や、解決された Issue への参照を含めることができます。

### Breaking Changes

Breaking Changes がある場合は、フッターに `BREAKING CHANGE:` というテキストを含め、その後に説明を続けます。または、タイプ/スコープの後に `!` を追加して示すこともできます。

例：
```
feat(homeassistant)!: change configuration format

BREAKING CHANGE: The configuration format has been changed to support new features.
```

### Issue の参照

解決された Issue への参照を含める場合は、以下のように記述します：

```
fix(mosquitto): correct connection timeout

Closes #123
```

## 例

### 新機能の追加
```
feat(ubuntu): add ghostty terminal support
```

### バグ修正
```
fix(docker): resolve container startup issue
```

### ドキュメント更新
```
docs: update README with new installation instructions
```

### 複数のロールに影響する変更
```
refactor: standardize task naming across roles
```

### Breaking Change を含む変更
```
feat(zabbix)!: upgrade to version 6.0

BREAKING CHANGE: This version requires new database schema.
```

## 注意事項

- コミットメッセージは英語で記述してください
- 1つのコミットでは1つの論理的な変更のみを行ってください
- コミットメッセージは明確で理解しやすいものにしてください
- 長い説明が必要な場合は、本文に詳細を記述してください
