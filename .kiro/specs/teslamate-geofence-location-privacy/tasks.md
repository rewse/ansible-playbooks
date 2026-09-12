# TeslaMateジオフェンス位置詳細非表示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GeoFence単位の`hide_details`設定で指定範囲内の住所と経路点を4つのGrafanaクエリから除外し、Forkの本体・Grafanaイメージをdigest固定でfoxへ段階配備してAnsibleの実行時パッチを撤去する。

**Architecture:** TeslaMate本体へboolean migration、Ecto field、LiveView switch、全19 localeの翻訳を追加し、Locations、Trip、Visited、Drive DetailsのSQLは`geofences.hide_details`を参照する空間`NOT EXISTS`で位置詳細だけを除外する。上流PR用ブランチは`upstream/main`から独立させ、Fork内PRでVampire Drain修正と統合した`rewse/teslamate:main`から本体・GrafanaをGHCRへ作る。Ansibleは本体を先に切り替えてmigrationを完了し、その後Grafanaを切り替えて2つのpatcher、抽出・変換タスク、4つのbind mountを削除する。

**Tech Stack:** Elixir 1.20.2-otp-29、Ecto、Phoenix LiveView 1.2.8、Gettext/Expo、PostgreSQL 18、`cube`/`earthdistance`、Grafana 13.2.1、GitHub Actions、GHCR、Ansible、Docker Compose、agent-browser

**Spec:** `.kiro/specs/teslamate-geofence-location-privacy/design.md`

## Global Constraints

- TeslaMate実装は`upstream/main`から作る`feat/hide-geofence-details`だけに置き、Vampire Drain修正やAnsible変更を上流PRへ混ぜない。
- Ansibleの現在の作業ツリーにはHome Assistantのユーザー変更があるため、実行時は`using-git-worktrees`相当の手順で別worktreeを作り、既存作業ツリーを変更・stash・commitしない。
- `Files`に記載した絶対pathはsource repositoryを識別するためのものとし、実際の編集は同じrepository-relative pathを隔離worktree内で行う。元のTeslaMate・Ansible worktreeを直接編集しない。
- 新しい依存関係は追加しない。PO検査には既存依存の`Expo.PO`と`Expo.Message.Singular`を使う。
- DB/Ecto fieldは`hide_details: boolean`、migrationは`NOT NULL DEFAULT false`、UI msgidは`Visibility`、`Hide location details`、設計書記載の補足文とする。
- 非表示対象はLocationsのAddressesとTrip、Visited、Drive Detailsの経路クエリだけとし、GeoFence名、Last visited、Geo-fences、集計、DBデータを維持する。
- 経路点を除外するだけとし、入口・出口のセグメント分割は実装しない。
- `ca`、`da`、`de`、`en`、`es`、`fi`、`fr`、`hu`、`it`、`ja`、`ko`、`nb`、`nl`、`sv`、`th`、`tr`、`uk`、`zh_Hans`、`zh_Hant`を更新し、英語以外の18 localeで新規3 msgidの`msgstr`を空にしない。
- 実住所、座標、車両ID、VIN、認証情報をcommit、PR本文、validation文書、スクリーンショットへ残さない。
- コードコメントとcommit messageは英語、specとplanは日本語で書く。commit messageはConventional Commitsに従う。
- macOS上のコンテナ確認は`container`、fox上は`docker`を使う。
- `git push`、GitHub Actions有効化、package公開、PR作成・merge、本番Playbook適用、実GeoFenceの設定変更は外部writeとして、その直前に明示承認を得る。
- `main`へ直接pushしない。Fork内PRを通して`rewse/teslamate:main`へ統合する。

---

## File Map

### TeslaMate Fork

- Create: `priv/repo/migrations/20260912100000_add_hide_details_to_geofences.exs`。`geofences.hide_details`を追加する。
- Modify: `lib/teslamate/locations/geo_fence.ex`。fieldの型、default、changeset castを定義する。
- Modify: `lib/teslamate_web/live/geofence_live/form.html.heex`。Visibility行、switch、補足文、ARIA関連付けを追加する。
- Modify: `test/teslamate/locations/geofences_test.exs`。既定値と更新のcontext testを追加する。
- Modify: `test/teslamate_web/live/geofence_live_test.exs`。描画、保存、解除、料金モーダル非表示を追加する。
- Modify: `test/teslamate_web/locale_test.exs`。18 localeの新規msgstr非空契約を追加する。
- Modify: `priv/gettext/default.pot`、`priv/gettext/*/LC_MESSAGES/default.po`。3 msgidを19 localeへ反映する。
- Modify: `test/teslamate/grafana/dashboard_queries_test.exs`。プライバシーフィルターが4ファイルに1件ずつある契約を追加する。
- Modify: `grafana/dashboards/locations.json`。Addressesだけをfilterする。
- Modify: `grafana/dashboards/trip.json`。route queryだけをfilterする。
- Modify: `grafana/dashboards/visited.json`。route queryだけをfilterする。
- Modify: `grafana/dashboards/internal/drive-details.json`。route queryだけをfilterする。

### Ansible

- Modify: `roles/teslamate/vars/main.yml`。検証済みFork本体・Grafanaのdigest付き参照を保持し、固定GeoFence名を削除する。
- Modify: `roles/teslamate/tasks/main.yml`。公式imageのquarantine解決、patcher配備、dashboard抽出・変換を削除する。
- Modify: `roles/teslamate/templates/compose.yml.j2`。4 dashboard mountを削除する。
- Modify: `roles/teslamate/tests/fixtures.yml`。GHCR fixture refsへ変更し、固定GeoFence名を削除する。
- Modify: `roles/teslamate/tests/render_templates.yml`。GHCR digest形式とmount不在を検証する。
- Delete: `roles/teslamate/files/patch_vampire_drain_dashboard.py`
- Delete: `roles/teslamate/files/patch_visited_dashboard.py`
- Delete: `roles/teslamate/tests/test_patch_vampire_drain_dashboard.py`
- Delete: `roles/teslamate/tests/test_patch_visited_dashboard.py`
- Create: `.kiro/specs/teslamate-geofence-location-privacy/validation.md`。匿名化した検証結果とrollback判定を記録する。

---

### Task 1: GeoFenceデータモデルを追加する

**Files:**
- Create: `/Users/tats/Playground/teslamate/priv/repo/migrations/20260912100000_add_hide_details_to_geofences.exs`
- Modify: `/Users/tats/Playground/teslamate/lib/teslamate/locations/geo_fence.ex:5-34`
- Test: `/Users/tats/Playground/teslamate/test/teslamate/locations/geofences_test.exs:7-120`

**Interfaces:**
- Consumes: `Locations.create_geofence(map()) :: {:ok, GeoFence.t()} | {:error, Ecto.Changeset.t()}`、`Locations.update_geofence(GeoFence.t(), map())`
- Produces: `%TeslaMate.Locations.GeoFence{hide_details: boolean()}`とDB column `geofences.hide_details boolean NOT NULL DEFAULT false`

- [ ] **Step 1: 隔離worktreeとfeature branchを準備する**

実行用skillでTeslaMate repositoryの隔離worktreeを作り、`upstream/main`から`feat/hide-geofence-details`を作成する。開始点を次で確認する。

```bash
git fetch upstream origin
git status --short --branch
git merge-base --is-ancestor upstream/main HEAD
git diff --quiet upstream/main...HEAD
```

Expected: branchが`feat/hide-geofence-details`、差分なし、元の`fix/vampire-drain-overlapping-states` worktreeはcleanのまま。

- [ ] **Step 2: fieldの既定値と更新を要求する失敗テストを書く**

`describe "geofences"`へ次を追加する。

```elixir
test "create_geofence/1 defaults hide_details to false" do
  assert {:ok, %GeoFence{} = geofence} = Locations.create_geofence(@valid_attrs)
  assert geofence.hide_details == false
end

test "update_geofence/2 updates hide_details" do
  geofence = geofence_fixture()

  assert {:ok, %GeoFence{} = geofence} =
           Locations.update_geofence(geofence, %{hide_details: true})

  assert geofence.hide_details == true
  assert Locations.get_geofence!(geofence.id).hide_details == true
end
```

- [ ] **Step 3: targeted testを実行してREDを確認する**

```bash
mix test test/teslamate/locations/geofences_test.exs
```

Expected: `%GeoFence{}`に`hide_details`がなく、compile errorまたはfield access errorでFAILする。

- [ ] **Step 4: migrationを追加する**

```elixir
defmodule TeslaMate.Repo.Migrations.AddHideDetailsToGeofences do
  use Ecto.Migration

  def change do
    alter table(:geofences) do
      add :hide_details, :boolean, null: false, default: false
    end
  end
end
```

- [ ] **Step 5: schemaとchangesetへfieldを追加する**

`radius`の後へfieldを置き、cast listでは位置fieldの後に追加する。

```elixir
field :hide_details, :boolean, default: false
```

```elixir
|> cast(attrs, [
  :name,
  :radius,
  :latitude,
  :longitude,
  :hide_details,
  :cost_per_unit,
  :session_fee,
  :billing_type
])
```

- [ ] **Step 6: migrationとtargeted testを実行してGREENを確認する**

```bash
MIX_ENV=test mix ecto.migrate
mix test test/teslamate/locations/geofences_test.exs
```

Expected: migrationが成功し、GeoFence testが全件PASSする。

- [ ] **Step 7: data modelをcommitする**

```bash
git add priv/repo/migrations/20260912100000_add_hide_details_to_geofences.exs \
  lib/teslamate/locations/geo_fence.ex \
  test/teslamate/locations/geofences_test.exs
git commit -m "feat(locations): add geofence detail visibility"
```

---

### Task 2: GeoFenceフォームへVisibility switchを追加する

**Files:**
- Modify: `/Users/tats/Playground/teslamate/lib/teslamate_web/live/geofence_live/form.html.heex:48-125`
- Test: `/Users/tats/Playground/teslamate/test/teslamate_web/live/geofence_live_test.exs:112-220,526-680`

**Interfaces:**
- Consumes: `GeoFence.hide_details`と`Locations.change_geofence/2`
- Produces: input `#geo_fence_hide_details`、help `#geo_fence_hide_details_help`、form param `geo_fence[hide_details]`

- [ ] **Step 1: 描画、保存、解除の失敗テストを書く**

`describe "Edit"`へ次を追加する。

```elixir
test "renders and updates location detail visibility", %{conn: conn} do
  %GeoFence{id: id} =
    geofence_fixture(%{
      name: "Private area",
      latitude: 52.514521,
      longitude: 13.350144,
      hide_details: true
    })

  assert {:ok, view, html} = live(conn, "/geo-fences/#{id}/edit")
  html = Floki.parse_document!(html)
  input = Floki.find(html, "#geo_fence_hide_details")

  assert ["checkbox"] = Floki.attribute(input, "type")
  assert Floki.attribute(input, "checked") != []
  assert ["geo_fence_hide_details_help"] = Floki.attribute(input, "aria-describedby")

  assert ["Visibility", "Hide location details"] =
           html
           |> Floki.find("label[for=geo_fence_hide_details]")
           |> Enum.map(&Floki.text/1)
           |> Enum.map(&String.trim/1)

  assert "Hide addresses in Locations and route points in Trip, Visited and Drive Details. The underlying location data remains stored." ==
           html
           |> Floki.find("#geo_fence_hide_details_help")
           |> Floki.text()
           |> String.trim()

  render_submit(view, :save, %{geo_fence: %{hide_details: "false"}})
  assert_redirect(view, "/geo-fences")
  assert Locations.get_geofence!(id).hide_details == false
end
```

`describe "New"`へ次を追加する。

```elixir
test "leaves location details visible by default", %{conn: conn} do
  assert {:ok, _view, html} = live(conn, "/geo-fences/new")

  assert [] =
           html
           |> Floki.parse_document!()
           |> Floki.find("#geo_fence_hide_details")
           |> Floki.attribute("checked")
end
```

- [ ] **Step 2: LiveView testを実行してREDを確認する**

```bash
mix test test/teslamate_web/live/geofence_live_test.exs
```

Expected: `#geo_fence_hide_details`が見つからずFAILする。

- [ ] **Step 3: NameとCostの間へswitchを追加する**

```heex
<div class="field is-horizontal">
  <div class="field-label is-normal is-paddingless">
    {label(f, :hide_details, gettext("Visibility"), class: "label")}
  </div>
  <div class="field-body">
    <div class="field">
      <div class="control">
        {checkbox(f, :hide_details,
          class: "switch is-rounded is-success",
          aria: [describedby: "geo_fence_hide_details_help"]
        )}
        {label(f, :hide_details, gettext("Hide location details"))}
      </div>
      <p id="geo_fence_hide_details_help" class="help">
        {gettext(
          "Hide addresses in Locations and route points in Trip, Visited and Drive Details. The underlying location data remains stored."
        )}
      </p>
    </div>
  </div>
</div>
```

`form.ex`の`position_or_cost_changed` listへ`:hide_details`を追加しない。

- [ ] **Step 4: 料金モーダルを開かず保存する失敗防止テストを書く**

`describe "charging cost"`へ次を追加する。

```elixir
test "does not show the charging cost modal when only visibility changes", %{conn: conn} do
  car = car_fixture()

  %GeoFence{id: id} =
    geofence_fixture(%{
      name: "Supercharger",
      latitude: 47.814441,
      longitude: 12.367768,
      radius: 30,
      billing_type: :per_kwh,
      cost_per_unit: 0.42,
      hide_details: false
    })

  :ok = insert_charging_processes(car, {47.81444104508753, 12.367612123489382})
  assert {:ok, view, _html} = live(conn, "/geo-fences/#{id}/edit")

  render_submit(view, :save, %{geo_fence: %{hide_details: "true"}})

  assert_redirect(view, "/geo-fences")
  assert Locations.get_geofence!(id).hide_details == true
end
```

- [ ] **Step 5: LiveView testsを実行してGREENを確認する**

```bash
mix test test/teslamate_web/live/geofence_live_test.exs
```

Expected: 全件PASSし、料金モーダル既存testも回帰しない。

- [ ] **Step 6: UI変更をcommitする**

```bash
git add lib/teslamate_web/live/geofence_live/form.html.heex \
  test/teslamate_web/live/geofence_live_test.exs
git commit -m "feat(web): add geofence detail visibility control"
```

---

### Task 3: 19 localeの翻訳を完成させる

**Files:**
- Modify: `/Users/tats/Playground/teslamate/test/teslamate_web/locale_test.exs:1-164`
- Modify: `/Users/tats/Playground/teslamate/priv/gettext/default.pot`
- Modify: `/Users/tats/Playground/teslamate/priv/gettext/{ca,da,de,en,es,fi,fr,hu,it,ja,ko,nb,nl,sv,th,tr,uk,zh_Hans,zh_Hant}/LC_MESSAGES/default.po`

**Interfaces:**
- Consumes: 3つのGettext msgidと`TeslaMateWeb.Plugs.Locale.gettext_locales/0 :: [String.t()]`
- Produces: 19 localeのPO entry。`en`はmsgid fallback、他18 localeは非空msgstr

- [ ] **Step 1: 新規翻訳の非空契約を追加する**

`TeslaMateWeb.LocaleTest`へmodule attributeとtestを追加する。

```elixir
@location_privacy_msgids [
  "Visibility",
  "Hide location details",
  "Hide addresses in Locations and route points in Trip, Visited and Drive Details. The underlying location data remains stored."
]

test "location privacy controls are translated in every non-English locale" do
  locales = TeslaMateWeb.Plugs.Locale.gettext_locales() -- ["en"]
  gettext_root = Path.expand("../../priv/gettext", __DIR__)

  for locale <- locales do
    translations =
      [gettext_root, locale, "LC_MESSAGES", "default.po"]
      |> Path.join()
      |> Expo.PO.parse_file!(strip_meta: true)
      |> Map.fetch!(:messages)
      |> Enum.reduce(%{}, fn
        %Expo.Message.Singular{msgid: msgid, msgstr: msgstr}, acc ->
          Map.put(acc, IO.iodata_to_binary(msgid), IO.iodata_to_binary(msgstr))

        _message, acc ->
          acc
      end)

    for msgid <- @location_privacy_msgids do
      assert Map.fetch!(translations, msgid) != "",
             "#{locale} has no translation for #{inspect(msgid)}"
    end
  end
end
```

- [ ] **Step 2: locale testを実行してREDを確認する**

```bash
mix test test/teslamate_web/locale_test.exs
```

Expected: 新規msgidがPOにないため`Map.fetch!/2`でFAILする。

- [ ] **Step 3: POTと全POへmsgidを抽出する**

```bash
mix gettext.extract --merge
```

Expected: `default.pot`と19個の`default.po`へ3 entryが追加され、英語以外は空msgstrのためtestはまだFAILする。

- [ ] **Step 4: 18 localeへ次の翻訳を設定する**

Dashboard名のLocations、Trip、Visited、Drive Detailsは製品内の固有表示として原文を維持する。

| Locale | Visibility | Hide location details | Help text |
|---|---|---|---|
| `ca` | Visibilitat | Amaga els detalls de la ubicació | Amaga les adreces a Locations i els punts de la ruta a Trip, Visited i Drive Details. Les dades d'ubicació subjacents continuen emmagatzemades. |
| `da` | Synlighed | Skjul placeringsoplysninger | Skjul adresser i Locations og rutepunkter i Trip, Visited og Drive Details. De underliggende placeringsdata gemmes fortsat. |
| `de` | Sichtbarkeit | Standortdetails ausblenden | Adressen in Locations und Routenpunkte in Trip, Visited und Drive Details ausblenden. Die zugrunde liegenden Standortdaten bleiben gespeichert. |
| `es` | Visibilidad | Ocultar detalles de ubicación | Oculta las direcciones en Locations y los puntos de ruta en Trip, Visited y Drive Details. Los datos de ubicación subyacentes permanecen almacenados. |
| `fi` | Näkyvyys | Piilota sijainnin tiedot | Piilota osoitteet Locations-näkymässä ja reittipisteet Trip-, Visited- ja Drive Details -näkymissä. Taustalla olevat sijaintitiedot säilytetään. |
| `fr` | Visibilité | Masquer les détails de localisation | Masque les adresses dans Locations et les points d'itinéraire dans Trip, Visited et Drive Details. Les données de localisation sous-jacentes restent enregistrées. |
| `hu` | Láthatóság | Helyadatok elrejtése | Elrejti a címeket a Locations, valamint az útvonalpontokat a Trip, Visited és Drive Details nézetben. A mögöttes helyadatok továbbra is tárolva maradnak. |
| `it` | Visibilità | Nascondi i dettagli della posizione | Nasconde gli indirizzi in Locations e i punti del percorso in Trip, Visited e Drive Details. I dati di posizione sottostanti restano memorizzati. |
| `ja` | 表示 | 位置情報の詳細を非表示 | Locationsの住所とTrip、Visited、Drive Detailsの経路点を非表示にする。元の位置データは保存される。 |
| `ko` | 표시 여부 | 위치 세부 정보 숨기기 | Locations의 주소와 Trip, Visited 및 Drive Details의 경로 지점을 숨깁니다. 원본 위치 데이터는 계속 저장됩니다. |
| `nb` | Synlighet | Skjul posisjonsdetaljer | Skjul adresser i Locations og rutepunkter i Trip, Visited og Drive Details. De underliggende posisjonsdataene lagres fortsatt. |
| `nl` | Zichtbaarheid | Locatiedetails verbergen | Verberg adressen in Locations en routepunten in Trip, Visited en Drive Details. De onderliggende locatiegegevens blijven opgeslagen. |
| `sv` | Synlighet | Dölj platsinformation | Dölj adresser i Locations och ruttpunkter i Trip, Visited och Drive Details. Underliggande platsdata sparas fortfarande. |
| `th` | การมองเห็น | ซ่อนรายละเอียดตำแหน่ง | ซ่อนที่อยู่ใน Locations และจุดเส้นทางใน Trip, Visited และ Drive Details โดยข้อมูลตำแหน่งต้นฉบับยังคงถูกจัดเก็บไว้ |
| `tr` | Görünürlük | Konum ayrıntılarını gizle | Locations içindeki adresleri ve Trip, Visited ile Drive Details içindeki rota noktalarını gizler. Temel konum verileri saklanmaya devam eder. |
| `uk` | Видимість | Приховати відомості про місцезнаходження | Приховує адреси в Locations і точки маршруту в Trip, Visited та Drive Details. Основні дані про місцезнаходження й надалі зберігаються. |
| `zh_Hans` | 可见性 | 隐藏位置详情 | 隐藏 Locations 中的地址以及 Trip、Visited 和 Drive Details 中的路线点。底层位置数据仍会保留。 |
| `zh_Hant` | 可見性 | 隱藏位置詳細資訊 | 隱藏 Locations 中的地址以及 Trip、Visited 和 Drive Details 中的路線點。底層位置資料仍會保留。 |

`en/LC_MESSAGES/default.po`はmsgid fallbackを使うため、新規entryのmsgstrを空のままにする。

- [ ] **Step 5: locale契約とGettext freshnessをGREENにする**

```bash
mix test test/teslamate_web/locale_test.exs
mix gettext.extract --check-up-to-date
```

Expected: 18 localeの3 msgstrが非空で、POT/POが最新としてPASSする。

- [ ] **Step 6: 翻訳変更をcommitする**

```bash
git add test/teslamate_web/locale_test.exs priv/gettext/default.pot priv/gettext/*/LC_MESSAGES/default.po
git commit -m "feat(i18n): translate geofence privacy controls"
```

---

### Task 4: 4つのGrafanaクエリへ空間filterを追加する

**Files:**
- Modify: `/Users/tats/Playground/teslamate/test/teslamate/grafana/dashboard_queries_test.exs:1-170`
- Modify: `/Users/tats/Playground/teslamate/grafana/dashboards/locations.json:900-930`
- Modify: `/Users/tats/Playground/teslamate/grafana/dashboards/trip.json:175-190`
- Modify: `/Users/tats/Playground/teslamate/grafana/dashboards/visited.json:170-185`
- Modify: `/Users/tats/Playground/teslamate/grafana/dashboards/internal/drive-details.json:625-640`

**Interfaces:**
- Consumes: `geofences.hide_details`、`earth_box(earth, float8)`、`earth_distance(earth, earth)`
- Produces: marker `-- Hide location details inside selected geo-fences`を持つ4つの`rawSql`

- [ ] **Step 1: filterの個数と構造を要求する失敗テストを書く**

module attributeとtestを追加する。

```elixir
@location_privacy_marker "-- hide location details inside selected geo-fences"
@location_privacy_paths %{
  "internal/drive-details.json" => 1,
  "locations.json" => 1,
  "trip.json" => 1,
  "visited.json" => 1
}

test "location privacy filter is limited to four detail queries" do
  matches =
    dashboard_directory_queries()
    |> Enum.filter(fn {_path, query} ->
      String.contains?(normalize(query), @location_privacy_marker)
    end)

  frequencies =
    matches
    |> Enum.map(fn {path, _query} -> Path.relative_to(path, @dashboard_directory) end)
    |> Enum.frequencies()

  assert frequencies == @location_privacy_paths

  for {_path, query} <- matches do
    query = normalize(query)
    assert query =~ "not exists ("
    assert query =~ "from geofences g"
    assert query =~ "where g.hide_details"
    assert query =~ "earth_box("
    assert query =~ "earth_distance("
    assert query =~ ") < g.radius"
  end
end
```

- [ ] **Step 2: dashboard query testを実行してREDを確認する**

```bash
mix test test/teslamate/grafana/dashboard_queries_test.exs
```

Expected: `frequencies`が空mapでFAILする。

- [ ] **Step 3: LocationsのAddresses rawSqlを置き換える**

```sql
SELECT
  CONCAT('new?lat=', a.latitude, '&lng=', a.longitude) as path,
  COALESCE(a.name, CONCAT(a.road, ' ', a.house_number)) AS name,
  a.neighbourhood,
  a.city,
  a.state,
  a.country
FROM addresses a
WHERE a.display_name ilike '%$address_filter%' and a.id in (
  select start_address_id from drives where car_id in ($car_id) and $__timeFilter(start_date)
  union
  select end_address_id from drives where car_id in ($car_id) and $__timeFilter(end_date)
  union
  select address_id from charging_processes where car_id in ($car_id) and ($__timeFilter(start_date) or $__timeFilter(end_date))
)
-- Hide location details inside selected geo-fences
AND NOT EXISTS (
  SELECT 1
  FROM geofences g
  WHERE g.hide_details
    AND earth_box(ll_to_earth(g.latitude, g.longitude), g.radius)
        @> ll_to_earth(a.latitude, a.longitude)
    AND earth_distance(
          ll_to_earth(g.latitude, g.longitude),
          ll_to_earth(a.latitude, a.longitude)
        ) < g.radius
)
ORDER BY a.inserted_at DESC
LIMIT 100;
```

- [ ] **Step 4: Tripのroute rawSqlを置き換える**

```sql
with unioned_positions as (

    -- fetch all positions based on start_date of drives so the map aligns with data shown in other panels
    select p.*
    from positions p
             inner join drives d on p.drive_id = d.id
    where p.car_id = $car_id and $__timeFilter(d.start_date)

    union all

    -- get all positions logged while not driving
    select *
    from positions p
    where p.car_id = $car_id and drive_id is null and $__timeFilter(date))

SELECT $__timeGroup(p.date, '5s') AS time,
       avg(p.latitude)            AS latitude,
       avg(p.longitude)           AS longitude
from unioned_positions p
-- Hide location details inside selected geo-fences
WHERE NOT EXISTS (
  SELECT 1
  FROM geofences g
  WHERE g.hide_details
    AND earth_box(ll_to_earth(g.latitude, g.longitude), g.radius)
        @> ll_to_earth(p.latitude, p.longitude)
    AND earth_distance(
          ll_to_earth(g.latitude, g.longitude),
          ll_to_earth(p.latitude, p.longitude)
        ) < g.radius
)
GROUP BY 1
ORDER BY 1 ASC
```

- [ ] **Step 5: Visitedのroute rawSqlを置き換える**

```sql
SELECT
  date_trunc('minute', timezone('UTC', p.date), '$__timezone') as time,
  avg(p.latitude) as latitude,
  avg(p.longitude) as longitude
FROM positions p
WHERE
  p.car_id = $car_id AND $__timeFilter(p.date) and p.ideal_battery_range_km is not null
  -- Hide location details inside selected geo-fences
  AND NOT EXISTS (
    SELECT 1
    FROM geofences g
    WHERE g.hide_details
      AND earth_box(ll_to_earth(g.latitude, g.longitude), g.radius)
          @> ll_to_earth(p.latitude, p.longitude)
      AND earth_distance(
            ll_to_earth(g.latitude, g.longitude),
            ll_to_earth(p.latitude, p.longitude)
          ) < g.radius
  )
GROUP BY 1
ORDER BY 1
```

- [ ] **Step 6: Drive Detailsのroute rawSqlを置き換える**

```sql
SELECT
  $__time(p.date),
  p.latitude,
  p.longitude
FROM positions p
WHERE
  p.car_id = $car_id AND
  $__timeFilter(p.date)
  -- Hide location details inside selected geo-fences
  AND NOT EXISTS (
    SELECT 1
    FROM geofences g
    WHERE g.hide_details
      AND earth_box(ll_to_earth(g.latitude, g.longitude), g.radius)
          @> ll_to_earth(p.latitude, p.longitude)
      AND earth_distance(
            ll_to_earth(g.latitude, g.longitude),
            ll_to_earth(p.latitude, p.longitude)
          ) < g.radius
  )
ORDER BY
  p.date ASC
```

JSONはGrafana 13.2.1のClassic model形式を維持し、対象`rawSql`以外を再formatしない。

- [ ] **Step 7: targeted testsとJSON parseを実行してGREENを確認する**

```bash
python3 -m json.tool grafana/dashboards/locations.json >/dev/null
python3 -m json.tool grafana/dashboards/trip.json >/dev/null
python3 -m json.tool grafana/dashboards/visited.json >/dev/null
python3 -m json.tool grafana/dashboards/internal/drive-details.json >/dev/null
mix test test/teslamate/grafana/dashboard_queries_test.exs
```

Expected: 4 JSONがparseでき、privacy path mapが4件でPASSする。

- [ ] **Step 8: dashboard変更をcommitする**

```bash
git add test/teslamate/grafana/dashboard_queries_test.exs \
  grafana/dashboards/locations.json \
  grafana/dashboards/trip.json \
  grafana/dashboards/visited.json \
  grafana/dashboards/internal/drive-details.json
git commit -m "feat(grafana): hide details inside selected geofences"
```

---

### Task 5: 合成SQL、全locale UI、Fork品質gateを通す

**Files:**
- Verify: Task 1から4のTeslaMate変更一式
- Temporary: `/tmp/geofence-location-privacy-cases.sql`

**Interfaces:**
- Consumes: 4 dashboard SQL、19 locale、`hide_details`
- Produces: synthetic predicate 0 mismatch、`mix ci`成功、2 viewport × 19 localeでoverflowなし

- [ ] **Step 1: 境界を含む合成SQLを作る**

```sql
CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;

WITH anchor AS (
  SELECT
    52.514521::double precision AS latitude,
    13.350144::double precision AS longitude,
    52.515421::double precision AS boundary_latitude,
    13.350144::double precision AS boundary_longitude
),
geofences(name, latitude, longitude, radius, hide_details) AS (
  SELECT
    'hidden',
    latitude,
    longitude,
    earth_distance(
      ll_to_earth(latitude, longitude),
      ll_to_earth(boundary_latitude, boundary_longitude)
    ),
    true
  FROM anchor
  UNION ALL
  SELECT 'visible-overlap', latitude, longitude, 1000::double precision, false FROM anchor
  UNION ALL
  SELECT 'visible-only', 48.137154, 11.576124, 1000::double precision, false
),
points(label, latitude, longitude, expected_visible) AS (
  SELECT 'inside-hidden', latitude, longitude, false FROM anchor
  UNION ALL
  SELECT 'on-boundary', boundary_latitude, boundary_longitude, true FROM anchor
  UNION ALL
  SELECT 'outside-all', 51.000000, 13.000000, true
  UNION ALL
  SELECT 'inside-visible-only', 48.137154, 11.576124, true
),
evaluated AS (
  SELECT
    p.*,
    NOT EXISTS (
      SELECT 1
      FROM geofences g
      WHERE g.hide_details
        AND earth_box(ll_to_earth(g.latitude, g.longitude), g.radius)
            @> ll_to_earth(p.latitude, p.longitude)
        AND earth_distance(
              ll_to_earth(g.latitude, g.longitude),
              ll_to_earth(p.latitude, p.longitude)
            ) < g.radius
    ) AS actual_visible
  FROM points p
)
SELECT label, expected_visible, actual_visible
FROM evaluated
WHERE expected_visible <> actual_visible;
```

- [ ] **Step 2: test DBで合成SQLを実行する**

```bash
MIX_ENV=test mix ecto.setup
psql teslamate_test -v ON_ERROR_STOP=1 -qAtf /tmp/geofence-location-privacy-cases.sql
```

Expected: mismatch rowが0件でstdoutが空になる。

- [ ] **Step 3: TeslaMate全品質gateを実行する**

```bash
mix gettext.extract --check-up-to-date
mix ci
nix run .#lint
```

Expected: format、unused dependency、全test、treefmtがPASSする。

- [ ] **Step 4: local Phoenixを起動する**

```bash
iex -S mix phx.server
```

Expected: `http://localhost:4000/geo-fences/new`が200で開く。別terminalで次のStepを実行する。

- [ ] **Step 5: 19 localeをdesktop/mobileでDOM検査する**

```bash
SESSION="$(agent-browser session id --scope worktree --prefix geofence-i18n)"
LOCALES=(ca da de en es fi fr hu it ja ko nb nl sv th tr uk zh_Hans zh_Hant)
for size in "1123 1683" "375 812"; do
  set -- $size
  agent-browser --session "$SESSION" set viewport "$1" "$2"
  for locale in "${LOCALES[@]}"; do
    agent-browser --session "$SESSION" open "http://localhost:4000/geo-fences/new?locale=$locale"
    agent-browser --session "$SESSION" wait --load networkidle
    cat <<'EOF' | agent-browser --session "$SESSION" eval --stdin >/dev/null
(() => {
  const input = document.querySelector('#geo_fence_hide_details');
  const help = document.querySelector('#geo_fence_hide_details_help');
  const labels = [...document.querySelectorAll('label[for="geo_fence_hide_details"]')];
  if (!input || !help || labels.length !== 2) throw new Error('privacy controls missing');
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth) {
    throw new Error('horizontal overflow');
  }
  for (const element of [help, ...labels]) {
    const rect = element.getBoundingClientRect();
    if (rect.right > document.documentElement.clientWidth || rect.left < 0) {
      throw new Error('privacy copy clipped');
    }
  }
  return true;
})()
EOF
  done
done
agent-browser --session "$SESSION" close
```

Expected: 38 renderすべてexit 0。LightpandaでLiveViewまたはLeafletが失敗した場合だけChrome engineへ切り替えて同じ検査を再実行する。

- [ ] **Step 6: feature branchの差分を確認する**

```bash
git diff --check upstream/main...HEAD
git -P log --oneline upstream/main..HEAD | cat
git -P diff --stat upstream/main...HEAD | cat
```

Expected: Task 1から4のTeslaMate関連ファイルだけで、Vampire Drain commitとAnsibleファイルを含まない。

---

### Task 6: Fork内PRで統合しGHCRイメージを生成する

**Files:**
- Existing: `/Users/tats/Playground/teslamate/.github/workflows/ghcr_build.yml`
- Existing: `/Users/tats/Playground/teslamate/.github/actions/build/action.yml`
- Existing: `/Users/tats/Playground/teslamate/.github/actions/grafana/action.yml`
- Produce: `/tmp/teslamate-fork-image-refs.env`

**Interfaces:**
- Consumes: `feat/hide-geofence-details`、`fix/vampire-drain-overlapping-states`、Fork Actions
- Produces: `TESLAMATE_IMAGE_REF`と`TESLAMATE_GRAFANA_IMAGE_REF`を持つenv file。どちらも`ghcr.io/rewse/teslamate...:main@sha256:`形式

- [ ] **Step 1: 外部writeの承認を得る**

GitHub Actions有効化、feature/integration branch push、Fork内PR作成・merge、GHCR package public化を列挙して明示承認を得る。未承認ならこのTaskで停止する。

- [ ] **Step 2: Fork Actionsを有効化してworkflowを確認する**

```bash
gh api --method PUT repos/rewse/teslamate/actions/permissions \
  --input - <<'JSON'
{"enabled":true,"allowed_actions":"all"}
JSON
gh api repos/rewse/teslamate/actions/workflows \
  --jq '{total_count, workflows: [.workflows[] | {name, path, state}]}'
```

Expected: `Build GHCR images`を含み、`total_count`が0より大きい。

- [ ] **Step 3: feature branchをoriginへpushする**

```bash
git push -u origin feat/hide-geofence-details
```

Expected: upstream tracking branchが設定される。

- [ ] **Step 4: integration branchへ2ブランチをmergeする**

別の隔離worktreeで次を実行する。

```bash
git fetch origin upstream
git switch -c integrate/geofence-location-privacy origin/main
git merge --no-ff fix/vampire-drain-overlapping-states \
  -m "Merge Vampire Drain fix for fork deployment"
git merge --no-ff feat/hide-geofence-details \
  -m "Merge geofence location privacy for fork deployment"
git diff --check origin/main...HEAD
```

Expected: conflictなし。Grafana imageにはPR #5729とlocation privacyの両変更、本体imageにはmigration/UI/翻訳が入る。

- [ ] **Step 5: Fork内PRを作成してchecksを待つ**

```bash
git push -u origin integrate/geofence-location-privacy
gh pr create \
  --repo rewse/teslamate \
  --base main \
  --head integrate/geofence-location-privacy \
  --title "Integrate geofence privacy and Grafana fixes" \
  --body $'Build the TeslaMate and Grafana images used by the rewse deployment.\n\nIncludes the isolated upstream changes for geofence detail visibility and Vampire Drain standby calculation.'
gh pr checks --repo rewse/teslamate --watch
```

Expected: Elixir、lint、GHCR本体build、Grafana buildが成功する。失敗時はmergeしない。

- [ ] **Step 6: merge承認を得てFork内PRをmergeする**

```bash
gh pr merge --repo rewse/teslamate --merge --delete-branch
```

Expected: `rewse/teslamate:main`が更新され、main pushのGHCR workflowが成功する。

- [ ] **Step 7: packageをpublicにして匿名pullを確認する**

```bash
gh auth refresh --hostname github.com --scopes write:packages
gh api --method PATCH /user/packages/container/teslamate -f visibility=public
gh api --method PATCH '/user/packages/container/teslamate%2Fgrafana' -f visibility=public
gh api '/users/rewse/packages?package_type=container&per_page=100' \
  --jq '.[] | select(.name == "teslamate" or .name == "teslamate/grafana") | [.name, .visibility] | @tsv'
```

Expected: 2 packageが`public`。public化できない場合は設計書どおり停止し、pull credentialを追加しない。

- [ ] **Step 8: amd64 manifestを確認してdigest refsを生成する**

```bash
for image in ghcr.io/rewse/teslamate:main ghcr.io/rewse/teslamate/grafana:main; do
  skopeo inspect --raw "docker://$image" |
    jq -e '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64")' >/dev/null
done

teslamate_digest="sha256:$(skopeo inspect --raw docker://ghcr.io/rewse/teslamate:main | shasum -a 256 | awk '{print $1}')"
grafana_digest="sha256:$(skopeo inspect --raw docker://ghcr.io/rewse/teslamate/grafana:main | shasum -a 256 | awk '{print $1}')"
cat > /tmp/teslamate-fork-image-refs.env <<EOF
TESLAMATE_IMAGE_REF=ghcr.io/rewse/teslamate:main@${teslamate_digest}
TESLAMATE_GRAFANA_IMAGE_REF=ghcr.io/rewse/teslamate/grafana:main@${grafana_digest}
EOF
source /tmp/teslamate-fork-image-refs.env
skopeo inspect "docker://$TESLAMATE_IMAGE_REF" >/dev/null
skopeo inspect "docker://$TESLAMATE_GRAFANA_IMAGE_REF" >/dev/null
```

Expected: env fileに2つの完全参照があり、どちらも匿名inspectできる。

---

### Task 7: AnsibleでFork本体だけを先行配備する

**Files:**
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/vars/main.yml:1-23`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tasks/main.yml:1-48`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/fixtures.yml:14-18`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/render_templates.yml:22-40`

**Interfaces:**
- Consumes: `/tmp/teslamate-fork-image-refs.env`の`TESLAMATE_IMAGE_REF`
- Produces: role var `teslamate_image_ref`がFork本体digest、Grafanaは既存公式digestとpatch構成を維持

- [ ] **Step 1: Ansible隔離worktreeを作る**

実行用skillで現在のAnsible `main`から`feat/teslamate-fork-images` worktreeを作る。元worktreeのHome Assistant差分が新worktreeに現れないことを確認する。

```bash
git status --short --branch
test -z "$(git status --porcelain)"
```

Expected: 新worktreeはcleanで、設計commitを含む。元worktreeのHome Assistant変更は元worktreeだけに残る。

- [ ] **Step 2: Fork本体image契約を先に失敗させる**

`render_templates.yml`のcompose contractへ追加する。

```yaml
- teslamate_test_compose.teslamate.image is match('^ghcr.io/rewse/teslamate:main@sha256:[0-9a-f]{64}$')
```

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: fixtureが`teslamate/teslamate`なのでassertがFAILする。

- [ ] **Step 3: 本体refをrole varsとfixtureへ設定する**

`/tmp/teslamate-fork-image-refs.env`をsourceし、`TESLAMATE_IMAGE_REF`の出力を文字列として`roles/teslamate/vars/main.yml`の`teslamate_image_ref`へ保存する。fixtureは固定test digestを使う。

```yaml
teslamate_image_ref: ghcr.io/rewse/teslamate:main@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

本番varsにはTask 6が生成したdigestを使用し、test用`a` digestを使わない。

- [ ] **Step 4: 公式本体image解決taskを削除する**

`Resolve TeslaMate image`と`Preserve TeslaMate image reference`の2 taskを削除する。後続taskの`teslamate_image_ref`条件とcompose interfaceは変更しない。Grafanaのquarantine taskはこの段階で残す。

- [ ] **Step 5: local Ansible検証をGREENにする**

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml --syntax-check
ansible-lint roles/teslamate/tasks/main.yml roles/teslamate/tests/render_templates.yml
rg -n 'quarantine_repo: teslamate/teslamate' roles/teslamate && exit 1 || true
```

Expected: contract、syntax、lintがPASSし、公式本体repo参照が0件。

- [ ] **Step 6: 本体先行変更をcommitする**

```bash
git add roles/teslamate/vars/main.yml \
  roles/teslamate/tasks/main.yml \
  roles/teslamate/tests/fixtures.yml \
  roles/teslamate/tests/render_templates.yml
git commit -m "feat(teslamate): deploy fork application image"
```

- [ ] **Step 7: 本番check modeの承認を得て実行する**

```bash
ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate \
  --check \
  --diff
```

Expected: TeslaMate本体image refと関連compose差分だけが予定され、Grafanaの公式refと4 mountは維持される。process exit code 0を確認する。

- [ ] **Step 8: 本番適用の承認を得て本体を切り替える**

```bash
ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate
```

Expected: process exit code 0。TeslaMateがFork digestで起動し、Grafanaは既存patch版のまま。

- [ ] **Step 9: migrationとUIを読み取り中心に検証する**

```bash
ssh fox.rewse.jp "docker inspect --format '{{.Config.Image}}' teslamate"
ssh fox.rewse.jp \
  "curl -fsS -o /dev/null -w '%{http_code}\n' -H 'Host: teslamate.rewse.jp' http://127.0.0.1:4001/health_check"
```

Expected: inspect結果がTask 6の本体ref、health checkが200。認証済み専用browser tabでGeoFence編集画面にVisibility switchと補足文が表示される。実GeoFenceの値はTask 9まで変更せず、まだGrafana表示検証へ進まない。

- [ ] **Step 10: 本体先行gateが失敗した場合だけrollbackする**

health、migration、UIのいずれかが失敗した場合はTask 8へ進まない。外部writeの承認を得たうえで、Task 7のcommitをrevertして公式本体image解決を戻し、check mode後に再適用する。

```bash
stage1_commit="$(git log -1 --format=%H --grep='^feat(teslamate): deploy fork application image$')"
test -n "$stage1_commit"
git revert --no-edit "$stage1_commit"
ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags teslamate --check --diff
ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags teslamate
```

Expected: 旧公式本体digestでサービスが回復する。追加済み`hide_details` columnは削除しない。失敗理由をvalidation記録へ残して停止する。成功時はこのStepでrevertしない。

---

### Task 8: Fork Grafanaへ切り替えてAnsible patchを撤去する

**Files:**
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/vars/main.yml:1-23`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tasks/main.yml:1-560`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/templates/compose.yml.j2:18-32`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/fixtures.yml:14-18`
- Modify: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/render_templates.yml:22-40`
- Delete: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/files/patch_vampire_drain_dashboard.py`
- Delete: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/files/patch_visited_dashboard.py`
- Delete: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/test_patch_vampire_drain_dashboard.py`
- Delete: `/Volumes/ExternalHD/git/ansible-playbooks/roles/teslamate/tests/test_patch_visited_dashboard.py`

**Interfaces:**
- Consumes: `/tmp/teslamate-fork-image-refs.env`の`TESLAMATE_GRAFANA_IMAGE_REF`とTask 7の本体ref
- Produces: patcher・dashboard mountなしの最終role、`teslamate_grafana_image_ref`がFork Grafana digest

- [ ] **Step 1: 最終compose契約を先に失敗させる**

`render_templates.yml`で既存4 mountのpositive assertを削除し、次を追加する。

```yaml
- teslamate_test_compose['teslamate-grafana'].image is match('^ghcr.io/rewse/teslamate/grafana:main@sha256:[0-9a-f]{64}$')
- "'grafana-dashboards' not in teslamate_test_compose_output"
```

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
```

Expected: 公式Grafana fixtureと4 mountが残っているためFAILする。

- [ ] **Step 2: Grafana refをrole varsとfixtureへ設定する**

本番varsにはTask 6の`TESLAMATE_GRAFANA_IMAGE_REF`を保存し、fixtureには次を使う。

```yaml
teslamate_grafana_image_ref: ghcr.io/rewse/teslamate/grafana:main@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

`teslamate_grafana_excluded_geofence`をvarsから削除し、`teslamate_grafana_image_digest_ref`を作るset_factと全参照をtasksから削除する。新しいimage ref変数は既存の同prefix変数とアルファベット順に置く。

- [ ] **Step 3: Grafana image解決とpatch pipelineを削除する**

`tasks/main.yml`から次を削除する。

- `Resolve Grafana image`
- `Preserve Grafana image reference`
- `Deploy Visited dashboard patcher`
- `Create Vampire Drain dashboard directory`
- `Deploy Vampire Drain dashboard patcher`
- `Check Grafana dashboard source image`
- `Pull Grafana dashboard source image`
- Visited/Trip/Drive Details用source container cleanup・extract block
- Vampire Drain用source container cleanup・extract block
- `Patch Vampire Drain dashboard`
- `Patch Grafana dashboards`

`Create data directories` loopから`grafana-dashboards` entryを削除する。ほかのTeslaMate data、Grafana永続data、import directoryは残す。

- [ ] **Step 4: composeの4 mountを削除する**

次のmountだけを削除し、`/var/lib/grafana`と`/etc/localtime`は残す。

```yaml
- {{ teslamate_data_dir }}/grafana-dashboards/drive-details.json:/dashboards_internal/drive-details.json:ro
- {{ teslamate_data_dir }}/grafana-dashboards/trip.json:/dashboards/trip.json:ro
- {{ teslamate_data_dir }}/grafana-dashboards/visited.json:/dashboards/visited.json:ro
- {{ teslamate_data_dir }}/grafana-dashboards/vampire-drain.json:/dashboards/vampire-drain.json:ro
```

- [ ] **Step 5: patcherとPython testsを削除し、host cleanupを追加する**

```bash
git rm roles/teslamate/files/patch_vampire_drain_dashboard.py \
  roles/teslamate/files/patch_visited_dashboard.py \
  roles/teslamate/tests/test_patch_vampire_drain_dashboard.py \
  roles/teslamate/tests/test_patch_visited_dashboard.py
```

`tasks/main.yml`の`Pull and update containers`より後へ、Fork Grafanaへの切り替えに成功した後だけ旧生成物を消すidempotent cleanupを追加する。新containerの更新が失敗した場合はこのtaskへ到達せず、旧mount用資材を維持する。

```yaml
- name: "teslamate : Remove legacy dashboard patch assets"
  ansible.builtin.file:
    path: "{{ item }}"
    state: absent
  loop:
    - "{{ teslamate_data_dir }}/patch_vampire_drain_dashboard.py"
    - "{{ teslamate_data_dir }}/patch_visited_dashboard.py"
    - "{{ teslamate_data_dir }}/grafana-dashboards"
  when:
    - teslamate_image_ref | length > 0
    - teslamate_grafana_image_ref | length > 0
  tags:
    - teslamate
    - config
    - update
    - docker
    - grafana
    - teslamate_docker
    - teslamate_docker_config
    - teslamate_docker_update
    - teslamate_grafana
    - teslamate_grafana_config
```

- [ ] **Step 6: 最終Ansible検証をGREENにする**

```bash
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml --syntax-check
ansible-lint roles/teslamate/tasks/main.yml roles/teslamate/tests/render_templates.yml
test ! -e roles/teslamate/files/patch_vampire_drain_dashboard.py
test ! -e roles/teslamate/files/patch_visited_dashboard.py
test ! -e roles/teslamate/tests/test_patch_vampire_drain_dashboard.py
test ! -e roles/teslamate/tests/test_patch_visited_dashboard.py
if rg -n 'Deploy .*dashboard patcher|Extract upstream .*dashboard|Patch (Vampire Drain|Grafana dashboards)|teslamate_grafana_excluded_geofence|quarantine_repo: teslamate/grafana' roles/teslamate; then
  exit 1
fi
if rg -n 'grafana-dashboards/.+:/dashboards' roles/teslamate/templates/compose.yml.j2; then
  exit 1
fi
```

Expected: contract、syntax、lintがPASSし、削除対象文字列が0件。

- [ ] **Step 7: 最終Ansible変更をcommitする**

```bash
git add roles/teslamate/vars/main.yml \
  roles/teslamate/tasks/main.yml \
  roles/teslamate/templates/compose.yml.j2 \
  roles/teslamate/tests/fixtures.yml \
  roles/teslamate/tests/render_templates.yml
git add -u roles/teslamate/files roles/teslamate/tests
git commit -m "feat(teslamate): deploy fork Grafana image"
```

- [ ] **Step 8: check modeの承認を得て差分を確認する**

```bash
ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate \
  --check \
  --diff
```

Expected: Grafana image ref、compose mount削除、不要patcher削除だけが主差分。DB・TeslaMate本体ref・他serviceは変えない。process exit code 0。

- [ ] **Step 9: 本番適用の承認を得てGrafanaを切り替える**

```bash
ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate
```

Expected: process exit code 0。GrafanaがFork digestで再作成される。

- [ ] **Step 10: container内容とmount不在を確認する**

```bash
ssh fox.rewse.jp "docker inspect --format '{{.Config.Image}}' teslamate-grafana"
ssh fox.rewse.jp "docker inspect --format '{{json .Mounts}}' teslamate-grafana" |
  jq -e 'all(.[]; ((.Destination | startswith("/dashboards")) | not))'
ssh fox.rewse.jp \
  "docker exec teslamate-grafana sh -c 'grep -R -l \"g.hide_details\" /dashboards /dashboards_internal'" |
  sort -u |
  wc -l
ssh fox.rewse.jp "test ! -e /srv/teslamate/grafana-dashboards && test ! -e /srv/teslamate/patch_vampire_drain_dashboard.py && test ! -e /srv/teslamate/patch_visited_dashboard.py"
```

Expected: Task 6のGrafana ref、dashboard mount 0、`g.hide_details`を含むdashboard file 4件。

---

### Task 9: 本番表示・性能・冪等性を検証して記録する

**Files:**
- Create: `/Volumes/ExternalHD/git/ansible-playbooks/.kiro/specs/teslamate-geofence-location-privacy/validation.md`
- Verify: TeslaMate、Grafana、Aurora PostgreSQL、Ansible role

**Interfaces:**
- Consumes: Task 7・8の本番配備、設計書の表示範囲と性能基準
- Produces: 個人情報を含まないvalidation記録、checkbox false→true→falseの復元証拠、Playbook 2回目changed=0

- [ ] **Step 1: 実GeoFence変更の承認を得る**

対象GeoFenceの`hide_details`を一時的にfalse→true→falseへ変更し、Grafanaへ問い合わせることを説明して明示承認を得る。承認がなければ読み取り検証だけ行い、設定を変更しない。

- [ ] **Step 2: false状態のbaselineを匿名化して取得する**

認証済み専用agent-browser tabでLocations、Trip、Visited、Drive Detailsを開く。走行中の追記で件数が変わらないよう、終了時刻を検証開始前に固定した過去期間を4 dashboardで共通使用する。次だけを一時メモリへ保持し、住所・座標・実時刻・車両ID・スクリーンショットを保存しない。

- Addresses対象行の有無
- 3 route queryの返却点数
- Last visitedとGeo-fencesにGeoFence名があること
- Grafana consoleとquery errorの有無

Expected: baselineでは住所と経路点が表示され、GeoFence名も表示される。

- [ ] **Step 3: trueへ変更して対象だけが消えることを確認する**

GeoFence編集画面で`Hide location details`を有効にして保存し、4 dashboardをrefreshする。

Expected: Locations Addressesの内部住所が消え、Trip、Visited、Drive Detailsの内部位置点が減る。# of Addresses、Cities、States、Last visited、Geo-fencesとGeoFence名は維持される。入口と出口を結ぶ線は判定対象外。

- [ ] **Step 4: falseへ戻して履歴が復元することを確認する**

switchを解除して保存し、4 dashboardをrefreshする。

Expected: baselineと同じ住所の有無とroute点数へ戻る。DBの履歴削除はない。

- [ ] **Step 5: 19 localeのproduction DOMを2 viewportで検証する**

Basic AuthはAnsibleと同じ1Password itemから一時Authorization headerとして設定し、credential、GeoFence名、座標をstdoutへ出さない。

```bash
SESSION="$(agent-browser session id --scope worktree --prefix geofence-production-i18n)"
USERNAME="$(direnv exec . op read 'op://ansible/vt2ez35yutq5ikwrbp46q56oke/username')"
PASSWORD="$(direnv exec . op read 'op://ansible/vt2ez35yutq5ikwrbp46q56oke/password')"
AUTH="$(printf '%s:%s' "$USERNAME" "$PASSWORD" | base64)"
HEADERS="$(AUTH="$AUTH" python3 - <<'PY_HEADERS'
import json
import os
print(json.dumps({"Authorization": "Basic " + os.environ["AUTH"]}))
PY_HEADERS
)"
unset USERNAME PASSWORD AUTH
LOCALES=(ca da de en es fi fr hu it ja ko nb nl sv th tr uk zh_Hans zh_Hant)
for size in "1123 1683" "375 812"; do
  set -- $size
  agent-browser --session "$SESSION" set viewport "$1" "$2"
  for locale in "${LOCALES[@]}"; do
    agent-browser --session "$SESSION" --headers "$HEADERS" \
      open "https://teslamate.rewse.jp/geo-fences/new?locale=$locale"
    agent-browser --session "$SESSION" wait --load networkidle
    cat <<'EOF' | agent-browser --session "$SESSION" eval --stdin >/dev/null
(() => {
  const input = document.querySelector('#geo_fence_hide_details');
  const help = document.querySelector('#geo_fence_hide_details_help');
  const labels = [...document.querySelectorAll('label[for="geo_fence_hide_details"]')];
  if (!input || !help || labels.length !== 2) throw new Error('privacy controls missing');
  if (document.documentElement.scrollWidth > document.documentElement.clientWidth) {
    throw new Error('horizontal overflow');
  }
  for (const element of [help, ...labels]) {
    const rect = element.getBoundingClientRect();
    if (rect.right > document.documentElement.clientWidth || rect.left < 0) {
      throw new Error('privacy copy clipped');
    }
  }
  return true;
})()
EOF
  done
done
unset HEADERS
agent-browser --session "$SESSION" close
```

Expected: 38 renderで3文字列が存在し、horizontal overflowとclippingがない。

- [ ] **Step 6: 4クエリのEXPLAINを修正前後で比較する**

本番Auroraへ接続して`BEGIN READ ONLY`から`ROLLBACK`までのtransaction内で、修正前は`git show upstream/main:<dashboard path>`、修正後はFork main imageと同じcommitのdashboardからrawSqlを取り出す。各rawSqlのGrafana変数を次のように固定したコピーを`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`で実行する。DB credentialは既存1Password参照から一時環境変数へ読み、command line、stdout、validation文書へ出さない。

- `$car_id`: `cars`から選んだ1件をpsql変数へ格納し、記録しない。
- `$__timeFilter(column)`: `column BETWEEN now() - interval '90 days' AND now()`
- `$__timeGroup(column, '5s')`: `date_bin('5 seconds', column, timestamp '2000-01-01')`
- `$__timezone`: `Asia/Tokyo`
- `$address_filter`: 空文字列
- Drive Details: 90日内の完了済みdrive 1件の開始・終了時刻をpsql変数へ格納し、記録しない。

各queryをウォームアップ1回後に3回実行し、median execution time、shared hit/read blocks、plan nodeを比較する。

Expected: 時刻・車両条件を越える新しい無制限`positions` scanがない。修正版medianが旧版の1.5倍を超え、かつ100ms以上増えた場合はFAILとしてTask 4へ戻る。

- [ ] **Step 7: TeslaMate/Grafana logを確認する**

```bash
ssh fox.rewse.jp "docker logs --since 30m teslamate 2>&1" | rg -i 'error|exception|migration' || true
ssh fox.rewse.jp "docker logs --since 30m teslamate-grafana 2>&1" | rg -i 'error|failed|pq:' || true
```

Expected: 今回のLiveView、migration、SQLに関するerrorが0件。無関係な既存warningは内容を区別して記録する。

- [ ] **Step 8: Playbook冪等性を確認する**

```bash
ansible-playbook singleton_int1.yml \
  --limit fox.rewse.jp \
  --tags teslamate
```

Expected: process exit code 0、対象hostの`changed=0`、`failed=0`。

- [ ] **Step 9: 最終gateが失敗した場合だけGrafana stageをrollbackする**

表示範囲、復元、SQL性能、logのいずれかが失敗した場合は上流PRへ進まない。`hide_details`をfalseへ戻し、外部writeの承認を得てTask 8のcommitをrevertし、公式Grafanaと4 mountを復元する。

```bash
stage2_commit="$(git log -1 --format=%H --grep='^feat(teslamate): deploy fork Grafana image$')"
test -n "$stage2_commit"
git revert --no-edit "$stage2_commit"
ansible-playbook -i localhost, -c local roles/teslamate/tests/render_templates.yml
ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags teslamate --check --diff
ansible-playbook singleton_int1.yml --limit fox.rewse.jp --tags teslamate
```

Expected: 旧公式Grafana digestと生成済みdashboard mountが復元される。DBの位置データと`hide_details` columnは保持する。成功時はこのStepでrevertしない。

- [ ] **Step 10: validation.mdを作成する**

次の見出しで、実値を匿名化して記録する。

```markdown
# TeslaMateジオフェンス位置詳細非表示の検証

## Forkとイメージ
## MigrationとUI
## 翻訳
## Grafana表示
## SQL性能
## Ansible配備と冪等性
## ロールバック判定
```

住所、座標、車両ID、VIN、実時刻、credential、スクリーンショットは書かない。digestとcommit SHAは公開情報なので記録する。

- [ ] **Step 11: validation記録をcommitする**

```bash
git add .kiro/specs/teslamate-geofence-location-privacy/validation.md
git commit -m "docs(teslamate): record geofence privacy validation"
```

---

### Task 10: 上流PRを準備して承認後に作成する

**Files:**
- Verify: `/Users/tats/Playground/teslamate`の`feat/hide-geofence-details`
- Temporary: `/tmp/teslamate-geofence-privacy-pr.md`

**Interfaces:**
- Consumes: Task 1から5のisolated feature commits、Task 9の匿名化検証結果
- Produces: `teslamate-org/teslamate`向け独立PR。Ansible・Vampire Drain commit・実データを含まない

- [ ] **Step 1: feature branchを最新upstream/mainへrebaseする**

```bash
git fetch upstream
git switch feat/hide-geofence-details
git rebase upstream/main
git diff --check upstream/main...HEAD
```

Expected: conflictなし。rebase後にforce pushが必要なら、明示承認を得て`git push --force-with-lease`だけを使う。`--force`は使わない。

- [ ] **Step 2: upstream提出前の全検証を再実行する**

```bash
mix gettext.extract --check-up-to-date
mix ci
nix run .#lint
python3 -m json.tool grafana/dashboards/locations.json >/dev/null
python3 -m json.tool grafana/dashboards/trip.json >/dev/null
python3 -m json.tool grafana/dashboards/visited.json >/dev/null
python3 -m json.tool grafana/dashboards/internal/drive-details.json >/dev/null
git diff --check upstream/main...HEAD
```

Expected: 全command exit 0。

- [ ] **Step 3: scopeを機械確認する**

```bash
git -P diff --name-only upstream/main...HEAD | cat
if git -P log --format='%H %s' upstream/main..HEAD | rg '1422deb|Vampire Drain'; then
  exit 1
fi
if git -P diff --name-only upstream/main...HEAD | rg '(^|/)roles/|ansible'; then
  exit 1
fi
```

Expected: migration、GeoFence model/form/tests、locale tests、default.pot、19 default.po、4 dashboard、Grafana query testだけ。

- [ ] **Step 4: PR本文を作る**

`/tmp/teslamate-geofence-privacy-pr.md`へ次の構成で書く。検証値はTask 9の匿名化結果を使い、実住所や座標を入れない。

```markdown
## Summary

- add a per-geofence setting that hides location details without deleting stored data
- omit addresses and route points from the four supported Grafana queries
- translate the new controls for every supported locale

## Behavior

Geo-fence names and aggregate panels remain visible. Disabling the setting restores historical addresses and route points because the underlying records are unchanged.

## Validation

- `mix ci`
- `nix run .#lint`
- Gettext extraction freshness and non-empty translations for 18 non-English locales
- synthetic inside, outside, overlap, and exact-boundary SQL cases
- `EXPLAIN (ANALYZE, BUFFERS)` comparison for all four queries
- desktop and mobile rendering for all 19 locales

## Privacy

The pull request contains no production addresses, coordinates, vehicle identifiers, or screenshots.

---

🤖 Assisted by GPT-5.6-sol (OpenAI) via Kiro CLI (planning, implementation, tests, and PR description).
```

- [ ] **Step 5: PR title・body・diffの承認を得る**

提案titleは`Add per-geofence location detail visibility`とする。`git diff --stat`、test結果、PR本文を提示し、明示承認なしに`gh pr create`を実行しない。

- [ ] **Step 6: branchをpushして上流PRを作る**

```bash
git push -u origin feat/hide-geofence-details
gh pr create \
  --repo teslamate-org/teslamate \
  --base main \
  --head rewse:feat/hide-geofence-details \
  --title "Add per-geofence location detail visibility" \
  --body-file /tmp/teslamate-geofence-privacy-pr.md
```

Expected: upstream PR URLが返る。PR checksを監視するが、mergeはupstream maintainerに任せる。

- [ ] **Step 7: FLAとreview対応を行う**

CLA AssistantがFLA 2.0を要求した場合はユーザーがGitHub上で署名する。substantive review replyには内容を確認したうえで同じAI支援footerを付け、ユーザー承認なしに代理投稿しない。

- [ ] **Step 8: 最終状態を確認する**

```bash
git status --short --branch
gh pr checks --repo teslamate-org/teslamate --watch
```

Expected: TeslaMate feature worktreeがclean、Ansible隔離worktreeがclean、既存Home Assistant作業ツリーの差分が保持され、上流PR checksが成功するか失敗理由が記録されている。
