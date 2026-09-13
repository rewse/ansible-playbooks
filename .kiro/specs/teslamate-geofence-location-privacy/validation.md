# TeslaMateジオフェンス位置詳細非表示の検証

## Forkとイメージ

TeslaMateとGrafanaはForkの統合commit `0f9e16c5` から生成した。TeslaMateは `ghcr.io/rewse/teslamate:main@sha256:eeb6841bf2b86d9ba03475400f61cb2655b4bf35c3bc20032ff1fe9b3fe76219`、Grafanaは `ghcr.io/rewse/teslamate/grafana:main@sha256:1617379d09ff97d5cdd1a920c43a85b7711e4ecb38b2f50479b2f280cc86fb4e` を本番で使用している。両コンテナは稼働中で、Grafanaに旧dashboard bind mountは残っていない。

Tripは、非表示対象GeoFenceの中心と境界を2つの`MATERIALIZED` CTEで先に計算する。位置点を扱うCTEはmaterializeせず、車両と期間による絞り込み、境界による候補選別、半径の厳密な判定を維持している。

## MigrationとUI

`hide_details` migrationの適用と既存GeoFenceの既定値 `false` を確認した。書き込みを始める前の早い段階では、brand-new cache-busted sessionで`Visibility`、`Hide location details`、`Hide addresses in Locations and route points in Trip, Visited and Drive Details. The underlying location data remains stored.`、checkboxの`false`を確認した。このsessionでは書き込みを行っていない。

最終的な挙動検証では、対象GeoFenceの値が`false`であることを別のDB readで確認してから、編集画面で`false→true→false`の順に保存した。各保存後に独立したDB接続で値を確認し、最後の値は`false`だった。

復元後の最適化済みイメージでは、さらに別のfresh sessionとcontroller checkを使った。行に正のgeometryがあり、2つのラベルが表示され、補足文が上記と完全に一致し、checkboxがuncheckedで、デスクトップとモバイルのどちらにも横方向のoverflowや文字切れがないことを確認した。長時間開いていた既存のLiveView tabは証拠に使わず、すべてfresh sessionで確認した。スクリーンショットは作成していない。

表示テストには、対象GeoFenceに関係する完了済みイベントから導出した過去期間を使った。期間の前後に余裕を持たせ、切り替え中は開始と終了を固定した。対象名、GeoFence ID、車両ID、住所、座標、実時刻は記録していない。

## 翻訳

本番の新規GeoFence画面を19 localeで開き、デスクトップとモバイルの2 viewportを使って合計38 renderを検証した。ラベル、checkbox、補足文、label関連付けが全renderに存在し、横方向のoverflowとclippingはなかった。

## Grafana表示

書き込み前に、Locationsの保存対象queryが対象GeoFence名を返すことをGrafana datasource APIで確認した。fresh sessionでGeo-fences panelを画面内へスクロールし、同じ名前が描画されていることも確認した。

`false`のbaselineではAddressesと各route queryがデータを返した。`true`ではAddresses、Trip、Visited、Drive Detailsの対象queryだけが減少した。Locationsの住所集計、Cities、States、Last visited、Geo-fencesとGeoFence名はbaselineと一致した。`false`へ戻した後、対象queryと維持対象queryの結果はbaselineへ完全に戻った。Grafana APIはquery errorを返さず、ブラウザconsoleにも検証を妨げるerrorはなかった。

## SQL性能

旧版はupstream baseline `03487fc7c7e6606da5bb8fc617c75fd2c386b7fe`、新版は稼働イメージと一致するFork統合commit `0f9e16c5` とした。Addresses、Trip、Visited、Drive Detailsの4 queryを2 versionで比較し、8組すべてをread-only transactionで実行した。各組はwarmup 1回と、ちょうど3回の測定で構成した。8/8の実行回数行がこの条件を満たした。

4 queryすべてで、複合性能閾値、boundedな実行経路と新しい無制限`positions` accessがないこと、結果形状の同等性を確認した。すべてPASSだった。生SQL、実パラメータ、生の性能値、実行計画は保存していない。

## Ansible配備と冪等性

挙動、復元、性能、logの確認後、最終最適化状態のTeslaMate対象Playbookを1回だけ実行した。process exit codeは0で、対象hostは `ok=16`、`changed=0`、`failed=0`、`unreachable=0` だった。実行後も上記2つの完全なイメージ参照が稼働していた。TeslaMateとGrafanaの各containerについて、最新起動以降に今回のLiveView保存、migration、Grafana SQLに関係するerrorはなかった。

## ロールバックと情報管理

表示範囲、`false`への復元、SQL性能、post-start log、Ansible冪等性の条件を満たしたため、Grafana stageのrollbackは行っていない。位置履歴は削除せず、イメージや構成にも追加変更を加えていない。

住所、GeoFence名やID、座標、実時刻、queryの実件数、生の性能値、実行計画、credentialは文書へ含めていない。一時検証データとsessionは削除またはcloseした。
