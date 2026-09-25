# 実装計画

- [x] 1. secrets.yaml.j2 テンプレートに REGZA API 認証情報を追加する
  - roles/homeassistant/templates/secrets.yaml.j2 に regza_username と regza_password を追加
  - vault_regza.username と vault_regza.password を使用
  - _要件: 4.1, 4.2_

- [ ] 2. RESTful センサーの設定を既存のファイルに追加する
  - [x] 2.1 binary_sensors.yaml ファイルを追加
    - roles/homeassistant/files/binary_sensors.yaml ファイルに RESTful センサーの設定を追加
    - roles/homeassistant/tasks/main.yml に binary_sensors.yaml を追加
    - _要件: 1.1, 2.1, 3.1_

  - [x] 2.2 バイナリセンサーの設定を実装する
    - REGZA Volume Muted センサーの設定を実装
    - ダイジェスト認証の設定
    - value_template で "on" の場合に true を返すように設定
    - _要件: 1.1, 1.2, 1.3, 1.4_

  - [x] 2.3 チャンネル情報センサーの設定を実装する
    - roles/homeassistant/files/sensors.yaml ファイルに REGZA Channel センサーの設定を実装
    - ダイジェスト認証の設定
    - value_template で channel_name を抽出するように設定
    - _要件: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.4 コンテンツタイプセンサーの設定を実装する
    - roles/homeassistant/files/sensors.yaml ファイルに REGZA Content Type センサーの設定を実装
    - ダイジェスト認証の設定
    - value_template で content_type を抽出するように設定
    - スキャン間隔を 5 秒に設定
    - _要件: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Ansible タスクの確認
  - [x] 3.1 main.yml を確認する
    - roles/homeassistant/tasks/main.yml で binary_sensors.yaml が適切に配置されることを確認
    - roles/homeassistant/tasks/main.yml で sensors.yaml が適切に配置されることを確認
    - 必要に応じて設定を修正
    - _要件: 4.1, 4.2_

- [ ] 4. テストと検証
  - [x] 4.1 設定の構文チェック
    - 作成した YAML ファイルの構文を確認
    - _要件: 4.2_

  - [ ] 4.2 ロールバック計画の作成
    - 問題が発生した場合のロールバック手順を文書化
    - _要件: 4.3_

- [ ] 5. 古い設定の削除
  - [x] 5.1 command_lines.yaml.j2 を修正する
    - roles/homeassistant/templates/command_lines.yaml.j2 から REGZA センサーを削除
    - 他のセンサーがある場合は残す
    - _要件: 4.1, 4.2, 4.3_
  
  - [x] 5.2 main.yml を修正する
    - roles/homeassistant/tasks/main.yml から command_lines.yaml.j2 の関連設定を削除
    - ファイルが空になる場合は、ファイルと関連タスクを完全に削除
    - _要件: 4.1, 4.2, 4.3_
