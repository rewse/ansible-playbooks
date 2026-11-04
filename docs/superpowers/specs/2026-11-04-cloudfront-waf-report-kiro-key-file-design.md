# cloudfront-waf-report の Kiro API キーを値だけのファイルにする設計

## 背景

`cloudfront-waf-report` は `/home/tats/.config/environment/kiro.sh` から `KIRO_API_KEY` を読む。このファイルは chezmoi が fox にだけ 0600 で置き、`export KIRO_API_KEY="..."` の 1 行を持つ。シェルはこのファイルを source せず、スクリプトの `read_api_key()` が正規表現 `^export KIRO_API_KEY="([^"]+)"$` で値を取り出している。

chezmoi では `~/.config/environment/` を、シェルが source する環境変数ファイルの置き場所にした（`cache.sh`、`gitlab.sh`、`teslamate.sh`）。`kiro.sh` だけはシェルに読まれず、シェルの書式を借りた鍵ファイルになっている。行の形を崩すとジョブが壊れる制約もある。

## ゴール

- Kiro API キーを、値だけを書いた `~/.config/cloudfront-waf-report/kiro-api-key` に置く。fox にだけ、0600 で置く。
- スクリプトはファイルの中身から前後の空白と改行を除いた文字列をキーとして使う。正規表現は使わない。
- `~/.config/environment/kiro.sh` を chezmoi の管理から外し、fox から消す。
- chezmoi の AGENTS.md から `kiro.sh` の例外の記述を消し、`~/.config/environment/` をシェルが source するファイルだけの場所にする。

## ゴールにしないこと

- ジョブを `tats` 以外のユーザーで動かすこと、AWS の認証情報をジョブ専用にすること。
- 1Password の項目の移動や、キーの再発行。

## 検討した方法

| 方法 | 利点 | 欠点 |
|---|---|---|
| A. `kiro.sh` のまま残す | 変更がない | シェルに読まれないファイルが `~/.config/environment/` に残り、行の形の制約も残る |
| B. root 所有の `/etc/credstore/kiro-api-key` を `LoadCredential=` で渡す | キーを読めるのが systemd とユニットだけになる | ジョブは `tats` で動き、`tats` の `~/.aws/credentials`（Route 53 の書き込み権限つき）も読めるので、守れる範囲がほとんど増えない。配布が ansible に移り、1Password の項目も `ansible` 保管庫へ移す必要がある |
| C. `tats` のホームに値だけのファイルを置く | 正規表現と行の形の制約がなくなる。配布は chezmoi のまま | 変更が chezmoi と ansible-playbooks にまたがる |

利用者は C を選んだ。置き場所は `~/.kiro` ではなく、ジョブ専用の `~/.config/cloudfront-waf-report/` にすることで合意した。`~/.kiro` は Kiro のエージェントが設定として読むので対話的な Kiro からキーが見えやすく、Kiro が中身を管理するディレクトリでもあり、Kiro 自身はキーをファイルから読まないためである。

## 決めたこと

- ファイルの持ち主は `tats` のままにする。
- 1Password の項目は `op://chezmoi/l2kqwiv5em4t4j2kxaat2py5fy/credential` のまま変えない。配るのは引き続き chezmoi である。
- `config.json` のキー名は `kiro_env_file` から `kiro_api_key_file` に変える（こちらの判断）。中身がシェルの環境変数ファイルではなくなるためである。
- 中身が空、または空白だけのファイルはエラーにする（こちらの判断）。空文字列を `KIRO_API_KEY` として kiro-cli に渡すと、原因のわかりにくい認証エラーになる。エラーの文言にはパスだけを入れ、値は入れない。
- fox 以外のホストでは、chezmoi の `.chezmoiignore` で `.config/cloudfront-waf-report` を除く（こちらの判断）。テンプレートを hostname の条件で空にするだけだと、ほかのホストに空のディレクトリができるためである。テンプレート自体は条件を持たない。

## 影響を受けるもの

| リポジトリ | ファイル | 変更 |
|---|---|---|
| ansible-playbooks | `roles/cloudfront_waf_report/files/cloudfront-waf-report` | `read_api_key()` を値だけのファイル向けにし、`_API_KEY` を消す。`config["kiro_api_key_file"]` を読む |
| ansible-playbooks | `roles/cloudfront_waf_report/templates/config.json.j2` | `kiro_api_key_file` を `/home/{{ admin_user }}/.config/cloudfront-waf-report/kiro-api-key` にする |
| ansible-playbooks | `tests/test_cloudfront_waf_report.py`、`tests/test_cloudfront_waf_report_role.py` | 新しい書式とキー名に合わせる |
| chezmoi | `dot_config/cloudfront-waf-report/private_kiro-api-key.tmpl` | 新規。値を 1 行出す |
| chezmoi | `.chezmoiignore` | fox 以外で `.config/cloudfront-waf-report` を除く |
| chezmoi | `dot_config/environment/private_kiro.sh.tmpl` | 削除し、`.chezmoiremove` に `.config/environment/kiro.sh` を足す |
| chezmoi | `AGENTS.md`、`tests/test_zprofile_path.py` | `kiro.sh` の例外の記述とテストの対象から外す |

`cloudfront-waf` の README にある Weekly report の説明はキーの置き場所に触れていないので、変えない。

## 切り替えの順序

古いスクリプトは `kiro.sh` を、新しいスクリプトは `kiro-api-key` を読む。ジョブは毎週土曜 07:47 に動くので、土曜の朝を避けて次の順で切り替える。

1. chezmoi の変更を push し、fox で `chezmoi apply` する。`kiro-api-key` ができ、`kiro.sh` が消える。
2. ansible-playbooks の変更を push し、Mac から `home-primary.yml` を `--tags cloudfront_waf_report` で fox に適用する。
3. fox で `sudo -u tats cloudfront-waf-report --dry-run` を動かす。`--dry-run` はメールを送らずに本文を表示する。件名が「AI 判定なし」でないことを確かめる。スクリプトは候補があるときだけキーを読むので、候補がない週はこれだけではキーの読み込みを確かめられないので、キーのファイルが空白以外の文字を持つことを、値を表示せずに確かめる。

1 と 2 の間はキーが読めない。その間にジョブが動いても、スクリプトはキーの読み込みの失敗を kiro-cli の判定の失敗として扱い、「AI 判定なし」のメールを送るので、レポートは止まらない。
