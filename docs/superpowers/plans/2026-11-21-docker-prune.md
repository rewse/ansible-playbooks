# Docker の未使用イメージ掃除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `roles/docker` に `prune` コンポーネントを足し、playbook の実行ごとに未使用のイメージと build cache を消す。

**Architecture:** `roles/docker/tasks/prune.yml` で `community.docker.docker_prune` を 1 回呼び、`tasks/main.yml` の最後で `docker_prune` と `update` のタグ付きで import する。docker ロールはサービスのロールより先に動くので、消えるのは前回の実行で置き換わった世代になる。

**Tech Stack:** Ansible、community.docker 5.4.0（`docker_prune`）、pytest（unittest 形式の契約テスト）

**Spec:** `docs/superpowers/specs/2026-11-21-docker-prune-design.md`

## Global Constraints

- 消す対象はイメージ（`images: true`、`images_filters: {dangling: false}`）と build cache（`builder_cache: true`、`builder_cache_all: true`）だけ。コンテナ、ネットワーク、ボリュームは消さない。
- タスク名は `prune | Remove unused images and build cache`。
- import のタグは `docker_prune` と `update`。
- check mode では何も消さない（`docker_prune` は check mode 非対応なので、Ansible がタスクを skip する）。

## Review Focus

- hotel の standby の `homeassistant` は停止中（Created）でも、そのイメージが残る。Task 1 Step 8 で確かめる。
- `--check` の実行は失敗せず、prune タスクが skipped になる。Task 1 Step 6 で確かめる。
- イメージを更新しない 2 回目の実行は `changed=0`。Task 1 Step 9 で確かめる。
- `--tags update` だけの実行でも prune が動く。Task 1 Step 1 のテスト `test_main_imports_prune_last_with_update_tag` で固定する。
- 将来 `containers` や `volumes` が足されて standby やデータが消える。Task 1 Step 1 のテスト `test_prune_touches_only_images_and_build_cache` で固定する。

---

### Task 1: prune コンポーネント

**Files:**
- Create: `roles/docker/tasks/prune.yml`
- Modify: `roles/docker/tasks/main.yml`（末尾に import を追加）
- Test: `tests/test_docker_prune.py`

**Interfaces:**
- Consumes: なし
- Produces: タグ `docker_prune`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_docker_prune.py` に、`tests/test_matterjs_server.py` と同じ unittest 形式で書く。`ROLE = REPO_ROOT / "roles" / "docker"`、`load_tasks(name)` は `yaml.safe_load` で読む。

```python
class PruneTest(unittest.TestCase):
    def test_prune_touches_only_images_and_build_cache(self):
        tasks = load_tasks("prune.yml")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "prune | Remove unused images and build cache")
        self.assertEqual(
            tasks[0]["community.docker.docker_prune"],
            {
                "builder_cache": True,
                "builder_cache_all": True,
                "images": True,
                "images_filters": {"dangling": False},
            },
        )

    def test_main_imports_prune_last_with_update_tag(self):
        last = load_tasks("main.yml")[-1]
        self.assertEqual(last["ansible.builtin.import_tasks"], "prune.yml")
        self.assertEqual(last["tags"], ["docker_prune", "update"])
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_docker_prune.py -v`
Expected: 2 件とも FAIL。`FileNotFoundError: ... roles/docker/tasks/prune.yml` と、`main.yml` の最後が `compose.yml` であることによる `AssertionError`

- [ ] **Step 3: `roles/docker/tasks/prune.yml` を書き、`tasks/main.yml` の末尾に `Import prune tasks` を足す**

`prune.yml` は `---` で始め、Step 1 のテストどおりの 1 タスクにする。タスクの上に、置き換わった世代は次の実行で消えることと、コンテナ・ボリュームを対象外にする理由（停止中の standby コンテナとデータを守る）をコメントで書く。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `uv run --with pytest --with ansible-core pytest tests/test_docker_prune.py -v`
Expected: 2 passed

- [ ] **Step 5: lint と全テストを通す**

Run: `git add tests/test_docker_prune.py roles/docker/tasks/prune.yml && uvx --with pre-commit-uv==4.3.0 pre-commit@4.6.2 run --all-files --show-diff-on-failure && uv run --with pytest --with ansible-core pytest tests`
Expected: pre-commit の全フックが Passed、pytest が全件 passed

- [ ] **Step 6: check mode で確かめる**

Run: `direnv exec . ansible-playbook home-secondary.yml --tags docker_prune --check --diff` と、同じく `home-primary.yml`
Expected: 終了コード 0。`prune | Remove unused images and build cache` が skipping

- [ ] **Step 7: 適用する**

Run: `direnv exec . ansible-playbook home-secondary.yml --tags docker_prune`、終わってから `home-primary.yml` で同じ
Expected: 終了コード 0。hotel は消す物がないので ok、fox は changed（未使用イメージと build cache 約 3.3GB を削除）

- [ ] **Step 8: 使用中のイメージが残ったことを確かめる**

Run: `ssh hotel 'sudo docker image ls; sudo docker ps -a --format "{{.Names}} {{.Image}} {{.Status}}"'` と、fox で `sudo docker ps -a --format "{{.Names}} {{.Image}} {{.Status}}"; sudo docker system df`
Expected: hotel に `homeassistant`（Created）のイメージ 1 個が残る。fox の全コンテナが元の状態のままで、Images の数がコンテナの使うイメージ数と同じ、Build Cache が 0B

- [ ] **Step 9: 2 回目が `changed=0` になることを確かめる**

Run: Step 7 と同じ 2 コマンドをもう一度
Expected: どちらも `changed=0`

- [ ] **Step 10: Commit**

```bash
git add roles/docker/tasks/main.yml roles/docker/tasks/prune.yml tests/test_docker_prune.py docs/superpowers/specs/2026-11-21-docker-prune-design.md docs/superpowers/plans/2026-11-21-docker-prune.md
git commit -m "fix: prune unused Docker images and build cache on every run"
```

main へのマージ時に、spec と plan を `docs/superpowers/archive/` に移す。
