# TeslaMateジオフェンス位置詳細非表示の検証

## Forkとイメージ

TeslaMateとGrafanaはForkの同じ統合commit `4a0bd5a` から生成した。TeslaMateは `ghcr.io/rewse/teslamate:main@sha256:47c926dd0fdbff31f221ec784abb6af062ede1ca760a25c86ebb75bc227aeeb6`、Grafanaは `ghcr.io/rewse/teslamate/grafana:main@sha256:6bc8752fe0273f96550bc7a76ee95c698d061205089032c6495a8be60b3a192c` を本番で使用している。両コンテナは稼働中で、Grafanaに旧dashboard bind mountは残っていない。

## MigrationとUI

`hide_details` migrationの適用と既存GeoFenceの既定値 `false` を確認した。承認済みの対象GeoFenceを編集画面から `false`、`true`、`false` の順で保存し、各保存後に別のDB接続で値を確認した。最後の値は `false` である。

表示テストには、対象GeoFenceに関連する最新の完了済み走行または充電イベントから導出した過去期間を使った。期間の前後に余裕を持たせ、切り替え中は開始時刻と終了時刻を固定した。対象名、GeoFence ID、車両ID、住所、座標、実時刻は記録していない。

## 翻訳

本番の新規GeoFence画面を対応する全localeで開き、デスクトップとモバイルの両viewportでラベル、checkbox、補足文、label関連付けを確認した。全renderで文字列が存在し、横方向のoverflowとclippingはなかった。スクリーンショットは作成していない。

## Grafana表示

書き込み前に、Locationsの保存対象queryが対象GeoFence名を返すことをGrafana datasource APIで確認した。brand-new browser sessionでもGeo-fences panelを画面内へスクロールし、fresh renderに同じ名前が含まれることを確認してから切り替えた。

`false` のbaselineではAddressesと各route queryがデータを返した。`true` ではAddresses、Trip、Visited、Drive Detailsの対象queryだけが減少した。Locationsの住所集計、Cities、States、Last visited、Geo-fencesとGeoFence名はbaselineと一致した。`false` へ戻した後、対象queryと維持対象queryの結果はbaselineへ完全に戻った。Grafana APIはquery errorを返さず、ブラウザconsoleにも検証を妨げるerrorはなかった。

## SQL性能

旧dashboardはupstream baseline `03487fc7c7e6606da5bb8fc617c75fd2c386b7fe`、新版は稼働イメージと一致するFork統合commit `4a0bd5a` から取得した。Addresses、Trip、Visited、Drive Detailsのraw SQLを本番Aurora PostgreSQLのread-only transactionで実行した。各版をウォームアップ後に複数回測定し、実行時間中央値、shared buffer、plan nodeを比較した。実パラメータ、実行時間、block数、plan本文は保存していない。

新版はいずれも「旧版の1.5倍超かつ100 ms以上増加」という失敗条件に該当しなかった。`positions` accessは車両と期間の条件内にあり、新しい無制限scanはなかった。

## Ansible配備と冪等性

挙動、復元、性能、logの確認後に、承認済みのTeslaMate対象Playbookを一度だけ実行した。process exit codeは0で、対象hostは `changed=0`、`failed=0`、`unreachable=0` だった。TeslaMateとGrafanaの各containerについて、最新起動以降に今回のLiveView保存、migration、Grafana SQLに関係するerrorはなかった。

## ロールバック判定

表示範囲、`false` への復元、SQL性能、post-start log、Ansible冪等性の条件を満たしたため、Grafana stageのrollbackは行っていない。位置履歴は削除しておらず、イメージや構成にも追加変更を加えていない。
