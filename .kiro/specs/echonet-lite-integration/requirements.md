# HEMS Echonet Lite integration 導入要件

## 機能要件

- Home Assistantに`sayurin/hems_echonet_lite`の安定リリース`v0.8.8`を導入する。
- integration domainは`echonet_lite`とし、ネットワークインターフェース`Auto`（`0.0.0.0`）で構成する。
- Rinnai MBC-342VをECHONET Liteのマルチキャスト探索で検出する。
- 瞬間式給湯器クラス`0x0272`が公開するentitiesをHome Assistantから参照できるようにする。

## 運用要件

- integrationのソースは既存のHome Assistant Ansibleロールで管理する。
- 検証済みのimmutable Git commitを変数で固定し、再実行可能なclone・synchronizeタスクとして実装する。
- 個別適用できる階層的なAnsible tagsを付ける。
- 機器IPの固定やDHCP reservationは必須要件にしない。
- HEMS版と従来版ECHONETLite Platformを同時に導入しない。

## 受け入れ条件

- Ansibleのsyntax checkが成功する。
- 対象tagsのcheck modeが成功する。
- 対象tagsの実適用が終了コード0で完了する。
- Home Assistant再起動後、`echonet_lite` config entryが`loaded`になる。
- `192.168.0.197`の機器に対応するdeviceが検出される。
- 対応entityが1件以上作成され、現在状態を取得できる。
- `echonet_lite`に関するsetup errorまたは反復例外がHome Assistantログにない。
