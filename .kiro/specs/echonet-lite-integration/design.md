# HEMS Echonet Lite integration 導入設計

## 目的

Home Assistant に HEMS Echonet Lite integration を導入し、Rinnai MBC-342V（現在のIPアドレス: `192.168.0.197`）をローカルネットワーク上で検出して利用可能にする。

## 採用方式

`sayurin/hems_echonet_lite` の安定リリース `v0.8.8` を採用する。Home Assistant 2026.3以降を対象とし、ECHONET Liteの瞬間式給湯器クラス `0x0272` を安定対応クラスとして扱うため、現在の Home Assistant Core 2026.8.3 と対象機器に適合する。

従来版 `scottyphillips/echonetlite_homeassistant` はRinnai機器の利用実績がある一方でメンテナンスモードであり、機器IPを個別設定する。新規導入では、開発が継続しておりマルチキャスト自動検出を行うHEMS版を優先する。

## 構成変更

既存のHome Assistant Ansibleロールのcustom integration管理方式に合わせる。

- `roles/homeassistant/vars/main.yml` に `v0.8.8` が指すimmutable commit SHA `2f17cf23bbfb2503cdc3cf239376bbfdc51fd02f` のバージョン変数を追加する。
- `roles/homeassistant/tasks/main.yml` にrootだけが書き込める`/var/lib/ansible/homeassistant`（mode `0700`）を作成し、リポジトリを指定commitでcloneするタスクを追加する。共有`/tmp`はcheckoutに使用しない。通常実行ではtracked変更を`force: true`で破棄し、`git clean -ffdx`でuntracked/ignoredファイルも除去して、同期元を固定commitと一致させる。check modeではAnsible標準の予測だけを行い、checkoutの変更・清掃・配置先同期は実行しない。
- `custom_components/echonet_lite` を `rsync --archive --delete` で `/srv/homeassistant/config/custom_components/echonet_lite` へ同期する。Home Assistantが生成する`__pycache__`と実行時に変化するdirectory mtimeは同期対象外とし、upstreamファイルが同一なら再起動を発生させない。旧式の隣接`*.pyc`は削除対象に残す。check modeではcheckoutと配置先を変更せず、同期を延期したことを報告する。
- ファイル更新時は既存のHome Assistant再起動handlerへ通知する。
- ECHONET Lite関連の階層的なAnsible tagsを付与し、個別適用できるようにする。

## ネットワーク

HEMS版は `224.0.23.0:3610/UDP` のマルチキャストで機器を自動検出する。Home Assistant Containerは既に `network_mode: host` で稼働し、対象機器と同じ `192.168.0.0/24` に接続している。

機器IPの固定やDHCP reservationは導入要件にしない。HEMS版は個別IPを永続設定しないため、`192.168.0.197` が変わっても再検出できる。運用上の識別を容易にする目的でDHCP reservationを設定してもよいが、本作業の範囲には含めない。

## 導入手順

1. Ansible構文検査とcheck modeで変更を検証する。
2. 対象ホストへECHONET Lite関連tagsを指定してロールを適用する。
3. Home Assistant再起動後、`echonet_lite` integrationをネットワークインターフェース `Auto`（`0.0.0.0`）で追加する。
4. 自動検出を待ち、MBC-342Vに対応するdeviceとentitiesを確認する。

## 検証

次の条件を満たした場合に導入完了とする。

- Home Assistantが `echonet_lite` custom integrationをロードできる。
- `echonet_lite` config entryが `loaded` 状態になる。
- `192.168.0.197` のECHONET Lite機器に対応するdeviceが検出される。
- 瞬間式給湯器クラス `0x0272` に由来するentitiesが1件以上作成され、状態を取得できる。
- Home Assistantのsystem/error logに `echonet_lite` のsetup errorまたは反復例外がない。

## 障害時の扱い

機器が検出されない場合は、integrationの再追加や別integrationの導入を直ちに行わず、次の順に切り分ける。

1. MBC-342V側でECHONET Liteが有効か確認する。
2. Home Assistantのbind先を `Auto` から `192.168.0.30` に変更して再検出する。
3. `224.0.23.0:3610/UDP` のマルチキャスト到達性とネットワーク機器のIGMP設定を確認する。
4. HEMS版で必要なEPCが公開されない場合に限り、従来版ECHONETLite Platform v4.0.8への切り替えを別変更として検討する。
