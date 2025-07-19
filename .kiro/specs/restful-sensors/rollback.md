# ロールバック計画

RESTful センサーの実装に問題が発生した場合のロールバック手順を以下に示します。

## 1. secrets.yaml.j2 のロールバック

secrets.yaml.j2 から REGZA API 認証情報を削除します：

```bash
# 以下の行を削除
regza_username: '[% vault_regza.username %]'
regza_password: '[% vault_regza.password %]'
```

## 2. binary_sensors.yaml のロールバック

binary_sensors.yaml ファイルから RESTful センサーの設定を削除します：

```bash
# 以下の行を削除
- platform: rest
  name: "REGZA Volume Muted"
  unique_id: binary_sensor.regza_volume_muted
  resource: http://regza/v2/remote/status/mute
  authentication: digest
  username: !secret regza_username
  password: !secret regza_password
  value_template: "{{ value_json.mute == 'on' }}"
  device_class: sound
```

## 3. sensors.yaml のロールバック

sensors.yaml ファイルから RESTful センサーの設定を削除します：

```bash
# 以下の行を削除
- platform: rest
  name: "REGZA Channel"
  unique_id: sensor.regza_channel
  resource: http://regza.rewse.jp/v2/remote/play/status
  authentication: digest
  username: !secret regza_username
  password: !secret regza_password
  value_template: "{{ value_json.epg_info_current.channel_name }}"
- platform: rest
  name: "REGZA Content Type"
  unique_id: sensor.regza_content_type
  resource: http://regza.rewse.jp/v2/remote/play/status
  authentication: digest
  username: !secret regza_username
  password: !secret regza_password
  value_template: "{{ value_json.content_type }}"
  scan_interval: 5
```

## 4. command_lines.yaml.j2 の復元

command_lines.yaml.j2 ファイルに元の設定を復元します：

```yaml
- binary_sensor:
    unique_id: binary_sensor.regza_volume_muted
    name: "REGZA Volume Muted"
    command: >-
        curl --digest --user '[% regza.username %]:[% regza.password %]' \
        http://regza/v2/remote/status/mute | jq -r .mute
# Do not use value_template because it causes a warning message every time
- sensor:
    unique_id: sensor.regza_channel
    name: "REGZA Channel"
    command: >-
        curl --digest --user '[% regza.username %]:[% regza.password %]' \
        http://regza.rewse.jp/v2/remote/play/status | jq -r .epg_info_current.channel_name
- sensor:
    unique_id: sensor.regza_content_type
    name: "REGZA Content Type"
    command: >-
        curl --digest --user '[% regza.username %]:[% regza.password %]' \
        http://regza.rewse.jp/v2/remote/play/status | jq -r .content_type
    scan_interval: 5
```

## 5. Ansible の実行

変更を適用するために Ansible を実行します：

```bash
ansible-playbook site.yml --tags homeassistant,homeassistant-component --limit "ホスト名"
```

または、特定のファイルだけを更新する場合：

```bash
ansible-playbook site.yml --tags homeassistant,homeassistant-component --limit "ホスト名" --start-at-task="Copy secrets.yaml"
```

## 6. Home Assistant の再起動

変更を適用するために Home Assistant を再起動します：

```bash
ansible-playbook site.yml --tags homeassistant --limit "ホスト名" --start-at-task="Restart homeassistant"
```

または、ホスト上で直接再起動する場合：

```bash
docker restart homeassistant
```
