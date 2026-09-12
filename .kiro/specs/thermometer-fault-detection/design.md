# 温湿度計故障検知の安定化設計

## 構成

各温湿度計にHome Assistantのstatisticsセンサーを追加し、`state_characteristic: average_step`と`max_age: 1 hour`で時間加重平均を求める。各部屋に平滑化後の差を評価するtemperature disagreementとhumidity disagreementを置き、`delay_on: 2 hours`で持続判定する。温度差のしきい値は1.5℃、湿度差のしきい値は10ポイントとする。

各部屋のthermometer faultとhygrometer faultは、非数値、範囲外、更新停止、または対応するdisagreementをOR条件で集約する。Dad’s RoomのSwitchBotはBluetooth距離による一時切断があるため、secondary sensorの非数値状態が30分継続した場合だけ故障条件へ含める。異常は即時反映し、`delay_off: 1 hour`で正常状態の持続を確認してから自動復旧する。鮮度は値の変化時刻ではなく`last_reported`で判断する。

温湿度差アラームは対応するfault binary sensorのoffからonへの遷移で通知する。Climate制御automationは両faultがoffであることを実行条件にし、アラームからautomation自体を無効化しない。これにより、内部クリーン復旧処理などがautomationを再有効化しても故障中の制御は再開しない。

## 対象

- Dad’s Room: AC温度調整、HeatCool遷移、モード変更、冷房・除湿切替、暖房切替
- Living Room: AC温度調整、HeatCool遷移、モード変更、冷房・除湿切替、暖房切替、床暖房切替
- Mom’s Room: AC温度調整、HeatCool遷移、モード変更、冷房・除湿切替、暖房切替

## 削除

3部屋の`humidity_difference`、`humidity_difference_average`、`temp_difference`、`temp_difference_average`を削除する。Balconyの差分・平均センサーは別用途で使用中のため維持する。

## 検証

Ansibleのlocalhostテストで平滑化センサー、故障センサー、アラーム、全停止対象automationの条件、旧センサーの不在を構造的に検証する。全変更YAMLをパースし、Home AssistantロールのAnsible構文チェックと実機テンプレート評価も実施する。
