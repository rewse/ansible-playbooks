"""Tests for the aged_release lookup plugin."""

import json
import os
import pathlib
import re
import sys
import time
from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
from ansible.errors import AnsibleLookupError

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "plugins" / "lookup")
)

import aged_release

NOW = datetime(2026, 9, 27, tzinfo=UTC)


@pytest.fixture(autouse=True)
def state_home(monkeypatch, tmp_path):
    """Keep the run cache of every test out of the real state directory."""
    home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    return home


def ago(days):
    return NOW - timedelta(days=days)


def iso(value):
    """Format a datetime, or a number of days before NOW, as RFC 3339."""
    dt = ago(value) if isinstance(value, int) else value
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeRun:
    """Answer commands and URLs from a table.

    A command is keyed by its joined argument list and a URL by itself, so one
    table serves both the run and the fetch the plugin is given.
    """

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, cmd):
        key = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.calls.append(key)
        if key not in self.table:
            raise AssertionError(f"unexpected command: {key}")
        value = self.table[key]
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)


def resolve(term, run, **kwargs):
    kwargs.setdefault("pattern", aged_release.DEFAULT_PATTERN)
    kwargs.setdefault("days", 4)
    kwargs.setdefault("platform", None)
    kwargs.setdefault("asset", None)
    return aged_release.resolve(term, run=run, fetch=run, now=NOW, **kwargs)


def inspect(image, arch="amd64"):
    return f"skopeo --override-os linux --override-arch {arch} inspect docker://{image}"


def hub(namespace, name, tag):
    return f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{name}/tags/{tag}"


def versions(kind, owner, name, page):
    return (
        f"gh api {kind}/{owner}/packages/container/{name}/versions"
        f"?per_page=100&page={page}"
    )


def version(digest, created):
    return {"name": digest, "created_at": iso(created)}


def release(tag, published, draft=False, prerelease=False, assets=()):
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": None if draft else iso(published),
        "assets": list(assets),
    }


def push(after, timestamp, activity_type="push", ref="refs/heads/master"):
    return {
        "activity_type": activity_type,
        "after": after,
        "ref": ref,
        "timestamp": iso(timestamp),
    }


TAGS = "gh api --paginate --slurp repos/o/r/tags?per_page=100"
RELEASES = "gh api --paginate --slurp repos/o/r/releases?per_page=100"
ACTIVITY = "gh api --paginate --slurp repos/o/r/activity?ref=refs/heads/{}&per_page=100"


def compare(base, head):
    return f"gh api repos/o/r/compare/{base}...{head}?per_page=1 --jq {{status}}"


def tag_run(tags, releases, statuses, head="h", pushed=5):
    """Answer a repository whose default branch main was at head pushed days ago.

    tags maps a tag to its commit, releases a tag to the days since its release
    was published, and statuses a commit to how head compares with it.
    """
    table = {
        TAGS: [[{"name": n, "commit": {"sha": s}} for n, s in tags.items()]],
        RELEASES: [[release(n, d) for n, d in releases.items()]],
        "gh api repos/o/r": {"default_branch": "main"},
        ACTIVITY.format("main"): [[push(head, pushed, ref="refs/heads/main")]],
    }
    for sha, status in statuses.items():
        table[compare(sha, head)] = (
            status if isinstance(status, Exception) else {"status": status}
        )
    return FakeRun(table)


def test_version_key_orders_numerically():
    assert aged_release.version_key("2025.10.1") > aged_release.version_key("2025.6.9")


def test_select_skips_too_new():
    candidates = [
        {"version": "1.2.0", "published": ago(3)},
        {"version": "1.1.0", "published": ago(5)},
    ]
    assert (
        aged_release.select(candidates, aged_release.DEFAULT_PATTERN, 4, NOW)["version"]
        == "1.1.0"
    )


def test_select_boundary_is_inclusive():
    candidates = [{"version": "1.0.0", "published": ago(4)}]
    assert (
        aged_release.select(candidates, aged_release.DEFAULT_PATTERN, 4, NOW)["version"]
        == "1.0.0"
    )


def test_select_filters_pattern():
    candidates = [
        {"version": "2.0.0-beta", "published": ago(10)},
        {"version": "1.9.0", "published": ago(10)},
    ]
    assert (
        aged_release.select(candidates, r"^\d+\.\d+\.\d+$", 4, NOW)["version"]
        == "1.9.0"
    )


def test_select_none_raises():
    with pytest.raises(AnsibleLookupError):
        aged_release.select(
            [{"version": "1.0.0", "published": ago(1)}],
            aged_release.DEFAULT_PATTERN,
            4,
            NOW,
        )


def test_oci_returns_tag_at_digest():
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/o/img": {
                "Tags": ["1.0.0", "1.1.0", "latest"]
            },
            "skopeo --override-os linux --override-arch arm64 inspect docker://ghcr.io/o/img:1.1.0": {
                "Created": iso(2),
                "Digest": "sha256:new",
            },
            "skopeo --override-os linux --override-arch arm64 inspect docker://ghcr.io/o/img:1.0.0": {
                "Created": iso(9),
                "Digest": "sha256:old",
            },
            "gh api users/o": {"type": "Organization"},
            versions("orgs", "o", "img", 1): [
                version("sha256:new", 2),
                version("sha256:old", 9),
            ],
        }
    )
    result = resolve("oci:ghcr.io/o/img", run, platform="linux/arm64")
    assert result == {"version": "1.0.0", "ref": "ghcr.io/o/img:1.0.0@sha256:old"}


def test_ghcr_backdated_created_does_not_skip_the_cooldown():
    # Created is written by whoever builds the image; GitHub's created_at is not.
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/o/img": {"Tags": ["1.0.0", "1.1.0"]},
            inspect("ghcr.io/o/img:1.1.0"): {
                "Created": iso(300),
                "Digest": "sha256:new",
            },
            inspect("ghcr.io/o/img:1.0.0"): {"Created": iso(9), "Digest": "sha256:old"},
            "gh api users/o": {"type": "Organization"},
            versions("orgs", "o", "img", 1): [
                version("sha256:new", 1),
                version("sha256:old", 9),
            ],
        }
    )
    assert resolve("oci:ghcr.io/o/img", run)["version"] == "1.0.0"


def test_ghcr_user_package_versions_are_read_across_pages():
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/u/a/b": {"Tags": ["1.0.0"]},
            inspect("ghcr.io/u/a/b:1.0.0"): {"Created": iso(9), "Digest": "sha256:x"},
            "gh api users/u": {"type": "User"},
            # A nested package name is one path segment in the API.
            versions("users", "u", "a%2Fb", 1): [
                version(f"sha256:{n}", 1) for n in range(100)
            ],
            versions("users", "u", "a%2Fb", 2): [version("sha256:x", 9)],
        }
    )
    assert resolve("oci:ghcr.io/u/a/b", run) == {
        "version": "1.0.0",
        "ref": "ghcr.io/u/a/b:1.0.0@sha256:x",
    }


def test_ghcr_digest_without_a_version_raises():
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/o/img": {"Tags": ["1.0.0"]},
            inspect("ghcr.io/o/img:1.0.0"): {"Created": iso(9), "Digest": "sha256:x"},
            "gh api users/o": {"type": "Organization"},
            versions("orgs", "o", "img", 1): [version("sha256:other", 9)],
        }
    )
    with pytest.raises(AnsibleLookupError, match="sha256:x"):
        resolve("oci:ghcr.io/o/img", run)


@pytest.mark.parametrize("status", ["403", "404"])
def test_ghcr_unreadable_versions_name_the_scope_to_add(status):
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/o/img": {"Tags": ["1.0.0"]},
            inspect("ghcr.io/o/img:1.0.0"): {"Created": iso(9), "Digest": "sha256:x"},
            "gh api users/o": {"type": "Organization"},
            versions("orgs", "o", "img", 1): RuntimeError(
                f"gh: You need at least read:packages scope (HTTP {status})"
            ),
        }
    )
    with pytest.raises(
        AnsibleLookupError, match=re.escape("gh auth refresh -s read:packages")
    ):
        resolve("oci:ghcr.io/o/img", run)


def test_docker_hub_backdated_created_does_not_skip_the_cooldown():
    run = FakeRun(
        {
            "skopeo list-tags docker://apache/couchdb": {"Tags": ["3.5.0", "3.5.1"]},
            inspect("apache/couchdb:3.5.1"): {
                "Created": iso(300),
                "Digest": "sha256:new",
            },
            inspect("apache/couchdb:3.5.0"): {
                "Created": iso(300),
                "Digest": "sha256:old",
            },
            hub("apache", "couchdb", "3.5.1"): {
                "digest": "sha256:new",
                "tag_last_pushed": iso(1),
            },
            hub("apache", "couchdb", "3.5.0"): {
                "digest": "sha256:old",
                "tag_last_pushed": iso(9),
            },
        }
    )
    assert resolve("oci:apache/couchdb", run) == {
        "version": "3.5.0",
        "ref": "apache/couchdb:3.5.0@sha256:old",
    }


def test_docker_hub_official_image_uses_the_library_namespace():
    run = FakeRun(
        {
            "skopeo list-tags docker://docker.io/couchdb": {"Tags": ["3.5.0"]},
            inspect("docker.io/couchdb:3.5.0"): {
                "Created": iso(9),
                "Digest": "sha256:x",
            },
            hub("library", "couchdb", "3.5.0"): {
                "digest": "sha256:x",
                "tag_last_pushed": iso(9),
            },
        }
    )
    assert resolve("oci:docker.io/couchdb", run)["version"] == "3.5.0"


def test_docker_hub_digest_mismatch_is_not_aged():
    # The tag moved between the two reads, so its push time is not the age of
    # the digest that would be pinned.
    run = FakeRun(
        {
            "skopeo list-tags docker://apache/couchdb": {"Tags": ["3.5.0", "3.5.1"]},
            inspect("apache/couchdb:3.5.1"): {"Created": iso(9), "Digest": "sha256:a"},
            inspect("apache/couchdb:3.5.0"): {"Created": iso(9), "Digest": "sha256:b"},
            hub("apache", "couchdb", "3.5.1"): {
                "digest": "sha256:other",
                "tag_last_pushed": iso(9),
            },
            hub("apache", "couchdb", "3.5.0"): {
                "digest": "sha256:b",
                "tag_last_pushed": iso(9),
            },
        }
    )
    assert resolve("oci:apache/couchdb", run)["version"] == "3.5.0"


def test_docker_hub_without_push_time_raises():
    run = FakeRun(
        {
            "skopeo list-tags docker://apache/couchdb": {"Tags": ["3.5.0"]},
            inspect("apache/couchdb:3.5.0"): {"Created": iso(9), "Digest": "sha256:x"},
            hub("apache", "couchdb", "3.5.0"): {
                "digest": "sha256:x",
                "tag_last_pushed": None,
            },
        }
    )
    with pytest.raises(AnsibleLookupError, match="push time"):
        resolve("oci:apache/couchdb", run)


def test_registry_without_push_times_raises():
    run = FakeRun(
        {
            "skopeo list-tags docker://quay.io/o/img": {"Tags": ["1.0.0"]},
            inspect("quay.io/o/img:1.0.0"): {"Created": iso(9), "Digest": "sha256:x"},
        }
    )
    with pytest.raises(AnsibleLookupError, match="quay.io"):
        resolve("oci:quay.io/o/img", run)


def test_oci_without_cooldown_reads_only_the_registry():
    # Images this account publishes are adopted at once, and no registry API
    # is asked, so their lookups need no extra token scope.
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/me/img": {"Tags": ["main"]},
            inspect("ghcr.io/me/img:main"): {"Created": iso(0), "Digest": "sha256:m"},
        }
    )
    assert resolve("oci:ghcr.io/me/img", run, pattern="^main$", days=0) == {
        "version": "main",
        "ref": "ghcr.io/me/img:main@sha256:m",
    }


def test_release_skips_draft_and_prerelease():
    run = FakeRun(
        {
            "gh api --paginate --slurp repos/o/r/releases?per_page=100": [
                [
                    {
                        "tag_name": "v3.0.0",
                        "draft": True,
                        "prerelease": False,
                        "published_at": iso(10),
                        "assets": [],
                    },
                    {
                        "tag_name": "v2.0.0",
                        "draft": False,
                        "prerelease": True,
                        "published_at": iso(10),
                        "assets": [],
                    },
                    {
                        "tag_name": "v1.0.0",
                        "draft": False,
                        "prerelease": False,
                        "published_at": iso(10),
                        "assets": [
                            {
                                "name": "a.js",
                                "browser_download_url": "https://x/a.js",
                                "updated_at": iso(10),
                                "digest": "sha256:aa",
                            }
                        ],
                    },
                ]
            ]
        }
    )
    assert resolve("github-release:o/r", run, asset="a.js")["version"] == "v1.0.0"


def test_release_asset_checksum():
    run = FakeRun(
        {
            "gh api --paginate --slurp repos/o/r/releases?per_page=100": [
                [
                    {
                        "tag_name": "v0.2.0",
                        "draft": False,
                        "prerelease": False,
                        "published_at": iso(10),
                        "assets": [
                            {
                                "name": "tool_0.2.0_linux_arm64.bz2",
                                "browser_download_url": "https://x/t.bz2",
                                "updated_at": iso(10),
                                "digest": "sha256:bb",
                            },
                            {
                                "name": "tool_0.2.0_linux_amd64.bz2",
                                "browser_download_url": "https://x/u.bz2",
                                "updated_at": iso(10),
                                "digest": "sha256:cc",
                            },
                        ],
                    },
                ]
            ]
        }
    )
    result = resolve("github-release:o/r", run, asset="tool_{version}_linux_arm64.bz2")
    assert result == {
        "version": "v0.2.0",
        "url": "https://x/t.bz2",
        "checksum": "sha256:bb",
    }


def test_release_without_digest_has_empty_checksum():
    run = FakeRun(
        {
            "gh api --paginate --slurp repos/o/r/releases?per_page=100": [
                [
                    {
                        "tag_name": "1.0.0",
                        "draft": False,
                        "prerelease": False,
                        "published_at": iso(10),
                        "assets": [
                            {
                                "name": "a.js",
                                "browser_download_url": "https://x/a.js",
                                "updated_at": iso(10),
                                "digest": None,
                            }
                        ],
                    },
                ]
            ]
        }
    )
    assert resolve("github-release:o/r", run, asset="a.js")["checksum"] == ""


def test_release_asset_updated_after_publication_counts_from_the_update():
    # An asset can be replaced long after its release was published.
    asset = {
        "name": "a.js",
        "browser_download_url": "https://x/a.js",
        "digest": "sha256:aa",
    }
    run = FakeRun(
        {
            RELEASES: [
                [
                    release("v2.0.0", 30, assets=[{**asset, "updated_at": iso(1)}]),
                    release("v1.0.0", 40, assets=[{**asset, "updated_at": iso(40)}]),
                ]
            ]
        }
    )
    assert resolve("github-release:o/r", run, asset="a.js")["version"] == "v1.0.0"


def test_tag_returns_commit_sha():
    run = tag_run(
        {"v1.1.0": "s11", "v1.0.0": "s10"},
        {"v1.1.0": 1, "v1.0.0": 30},
        {"s10": "ahead"},
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


def test_tag_backdated_commit_does_not_skip_the_cooldown():
    # The committer date is chosen by whoever pushes the tag; the release
    # publication time is recorded by GitHub.
    run = tag_run(
        {"v1.1.0": "s11", "v1.0.0": "s10"},
        {"v1.1.0": 1, "v1.0.0": 30},
        {"s10": "ahead"},
    )
    run.table["gh api repos/o/r/commits/s11"] = {
        "commit": {"committer": {"date": iso(300)}}
    }
    assert resolve("github-tag:o/r", run)["commit"] == "s10"


def test_tag_without_release_is_skipped():
    # Some projects publish a release under a different tag name, which leaves
    # a tag with no time to age it by.
    run = tag_run(
        {"v1.1.0": "s11", "v1.0.0": "s10"},
        {"v1.1.0-rel": 30, "v1.0.0": 40},
        {"s10": "ahead"},
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


def test_tag_without_release_raises_when_no_tag_has_one():
    run = FakeRun(
        {
            TAGS: [[{"name": "v1.0.0", "commit": {"sha": "s10"}}]],
            RELEASES: [[release("v1.0.0", 30, draft=True)]],
        }
    )
    with pytest.raises(AnsibleLookupError, match="no tag of o/r matching"):
        resolve("github-tag:o/r", run)


def test_tag_prerelease_counts_as_published():
    run = tag_run({"v0.9.1": "s"}, {}, {"s": "ahead"})
    run.table[RELEASES] = [[release("v0.9.1", 5, prerelease=True)]]
    assert resolve("github-tag:o/r", run) == {"version": "v0.9.1", "commit": "s"}


def test_tag_without_cooldown_needs_no_release():
    run = FakeRun(
        {
            TAGS: [[{"name": "v1.0.0", "commit": {"sha": "s10"}}]],
            "gh api repos/o/r/commits/s10": {"commit": {"committer": {"date": iso(0)}}},
        }
    )
    assert resolve("github-tag:o/r", run, days=0) == {
        "version": "v1.0.0",
        "commit": "s10",
    }


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_tag_on_a_commit_the_default_branch_held_is_taken(status):
    run = tag_run({"v1.0.0": "s10"}, {"v1.0.0": 30}, {"s10": status})
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_tag_on_a_commit_the_default_branch_did_not_hold_is_skipped(status):
    # An old release renamed to a new tag, or a tag moved after its release,
    # dates a commit that may have been pushed a minute ago.
    run = tag_run(
        {"v1.1.0": "fresh", "v1.0.0": "s10"},
        {"v1.1.0": 30, "v1.0.0": 30},
        {"fresh": status, "s10": "ahead"},
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


def test_tag_on_a_commit_with_no_shared_history_is_skipped():
    # GitHub answers 404 when the commits share no history.
    run = tag_run(
        {"v1.1.0": "orphan", "v1.0.0": "s10"},
        {"v1.1.0": 30, "v1.0.0": 30},
        {"orphan": RuntimeError("No common ancestor (HTTP 404)"), "s10": "ahead"},
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


def test_tag_moved_with_no_older_tag_raises():
    run = tag_run({"v1.0.0": "moved"}, {"v1.0.0": 30}, {"moved": "behind"})
    with pytest.raises(AnsibleLookupError, match="no tag of o/r matching"):
        resolve("github-tag:o/r", run)


def test_tag_is_checked_against_the_branch_head_at_the_cooldown():
    # The head pushed a day ago may already contain a commit pushed today; the
    # one pushed five days ago is what the branch held at the cooldown.
    run = tag_run({"v1.0.0": "s10"}, {"v1.0.0": 30}, {"s10": "ahead"}, head="old")
    run.table[ACTIVITY.format("main")] = [
        [push("new", 1, ref="refs/heads/main"), push("old", 5, ref="refs/heads/main")]
    ]
    assert resolve("github-tag:o/r", run)["commit"] == "s10"
    assert compare("s10", "new") not in run.calls


def test_tag_without_an_aged_push_to_the_default_branch_raises():
    run = tag_run({"v1.0.0": "s10"}, {"v1.0.0": 30}, {"s10": "ahead"}, pushed=1)
    with pytest.raises(AnsibleLookupError, match="no push to main at least 4 day"):
        resolve("github-tag:o/r", run)


def test_tag_reads_the_branch_only_for_an_aged_release():
    run = tag_run({"v1.0.0": "s10"}, {"v1.0.0": 1}, {})
    with pytest.raises(AnsibleLookupError, match="no tag of o/r matching"):
        resolve("github-tag:o/r", run)
    assert run.calls == [TAGS, RELEASES]


def test_tag_writes_no_state(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    run = tag_run({"v1.0.0": "s10"}, {"v1.0.0": 30}, {"s10": "ahead"})
    resolve("github-tag:o/r", run)
    assert list(tmp_path.iterdir()) == []


def test_commit_returns_newest_aged():
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [
                [push("fresh", 1), push("abc", 5), push("older", 9)]
            ],
        }
    )
    assert resolve("github-commit:o/r", run) == {"commit": "abc"}


def test_commit_boundary_is_inclusive():
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [[push("fresh", 1), push("abc", 4)]],
        }
    )
    assert resolve("github-commit:o/r", run) == {"commit": "abc"}


def test_commit_counts_merges_through_the_web_interface():
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [
                [
                    push("deleted", 5, "branch_deletion"),
                    push("merged", 6, "pr_merge"),
                    push("queued", 7, "merge_queue_merge"),
                ]
            ],
        }
    )
    assert resolve("github-commit:o/r", run) == {"commit": "merged"}


def test_commit_skips_branch_deletion():
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [
                [push("0" * 40, 5, "branch_deletion"), push("abc", 6)]
            ],
        }
    )
    assert resolve("github-commit:o/r", run) == {"commit": "abc"}


def test_commit_without_aged_push_raises():
    # A backdated commit pushed yesterday is still a push from yesterday.
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [[push("fresh", 1)]],
        }
    )
    with pytest.raises(AnsibleLookupError, match="no push"):
        resolve("github-commit:o/r", run)


def test_commit_without_cooldown_takes_the_branch_head():
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "main"},
            f"gh api repos/o/r/commits?sha=main&until={iso(NOW)}&per_page=1": [
                {"sha": "head"}
            ],
        }
    )
    assert resolve("github-commit:o/r", run, days=0) == {"commit": "head"}


def test_gh_failure_raises():
    run = FakeRun({TAGS: RuntimeError("HTTP 403: API rate limit exceeded")})
    with pytest.raises(AnsibleLookupError, match="rate limit"):
        resolve("github-tag:o/r", run)


def aged_head_run(branch="main"):
    return FakeRun(
        {
            "gh api repos/o/r": {"default_branch": branch},
            ACTIVITY.format(branch): [[push("abc", 5, ref=f"refs/heads/{branch}")]],
        }
    )


def test_lookup_caches_identical_calls(monkeypatch, tmp_path):
    run = aged_head_run()
    monkeypatch.setattr(aged_release, "_run", run)
    monkeypatch.setattr(aged_release, "_now", lambda: NOW)
    monkeypatch.setattr(
        aged_release, "_cache_path", lambda: pathlib.Path(tmp_path) / "cache.json"
    )
    aged_release._CACHE.clear()
    lookup = aged_release.LookupModule()
    variables = {"supply_chain_cooldown_days": 4}
    first = lookup.run(["github-commit:o/r"], variables)
    second = lookup.run(["github-commit:o/r"], variables)
    assert first == second == [{"commit": "abc"}]
    assert len(run.calls) == 2


def test_default_pattern_ignores_single_number_tags():
    run = tag_run({"14": "old", "v4.2.1": "new"}, {"v4.2.1": 10}, {"new": "ahead"})
    assert resolve("github-tag:o/r", run) == {"version": "v4.2.1", "commit": "new"}


def test_cache_is_shared_across_worker_processes(monkeypatch, tmp_path):
    run = aged_head_run()
    monkeypatch.setattr(aged_release, "_run", run)
    monkeypatch.setattr(aged_release, "_now", lambda: NOW)
    monkeypatch.setattr(aged_release, "_cache_path", lambda: tmp_path / "cache.json")
    variables = {"supply_chain_cooldown_days": 4}
    aged_release._CACHE.clear()
    aged_release.LookupModule().run(["github-commit:o/r"], variables)
    # Ansible templates each task in a freshly forked worker, so the in-memory
    # cache starts empty for the next task or host.
    aged_release._CACHE.clear()
    assert aged_release.LookupModule().run(["github-commit:o/r"], variables) == [
        {"commit": "abc"}
    ]
    assert len(run.calls) == 2


def test_run_cache_lives_in_the_state_directory(monkeypatch, state_home):
    run = aged_head_run()
    monkeypatch.setattr(aged_release, "_run", run)
    monkeypatch.setattr(aged_release, "_now", lambda: NOW)
    aged_release._CACHE.clear()
    aged_release.LookupModule().run(
        ["github-commit:o/r"], {"supply_chain_cooldown_days": 4}
    )
    directory = state_home / "aged_release"
    assert aged_release._cache_path().parent == directory
    assert aged_release._cache_path().is_file()
    assert directory.stat().st_mode & 0o777 == 0o700


def test_new_run_cache_removes_expired_run_caches(monkeypatch, state_home):
    directory = state_home / "aged_release"
    directory.mkdir(mode=0o700, parents=True)
    expired = directory / "run-1.json"
    recent = directory / "run-2.json"
    for path in (expired, recent):
        path.write_text("{}")
    old = time.time() - aged_release._CACHE_TTL.total_seconds() - 60
    os.utime(expired, (old, old))
    (directory / "other.json").write_text("{}")
    os.utime(directory / "other.json", (old, old))
    monkeypatch.setattr(aged_release, "_run", aged_head_run())
    monkeypatch.setattr(aged_release, "_now", lambda: NOW)
    aged_release._CACHE.clear()
    aged_release.LookupModule().run(
        ["github-commit:o/r"], {"supply_chain_cooldown_days": 4}
    )
    assert not expired.exists()
    assert recent.exists()
    assert (directory / "other.json").exists()


def test_release_error_names_repository():
    # The only release is one day old, so nothing is aged enough.
    run = FakeRun({RELEASES: [[release("v1.0", 1)]]})
    with pytest.raises(AnsibleLookupError, match="o/r: no version"):
        resolve("github-release:o/r", run)


def test_tags_are_read_across_pages():
    # Page 1 holds only a too-new tag; the aged one is on page 2.
    run = FakeRun(
        {
            TAGS: [
                [{"name": "v2.0", "commit": {"sha": "new"}}],
                [{"name": "v1.0", "commit": {"sha": "old"}}],
            ],
            RELEASES: [[release("v2.0", 1)], [release("v1.0", 5)]],
            "gh api repos/o/r": {"default_branch": "main"},
            ACTIVITY.format("main"): [[push("h", 5, ref="refs/heads/main")]],
            compare("old", "h"): {"status": "ahead"},
        }
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0", "commit": "old"}


def test_parse_time_honours_offset():
    assert aged_release._parse_time("2026-09-20T09:00:00+09:00") == datetime(
        2026, 9, 20, tzinfo=UTC
    )


def test_parse_time_accepts_nanoseconds_and_z():
    assert aged_release._parse_time("2026-09-20T00:00:00.123456789Z") == datetime(
        2026, 9, 20, 0, 0, 0, 123456, tzinfo=UTC
    )


def test_image_created_before_2000_is_rejected():
    # Without a cooldown the age comes from Created, which reproducible builds
    # set to the epoch.
    run = FakeRun(
        {
            "skopeo list-tags docker://ghcr.io/o/img": {"Tags": ["1.0.0"]},
            "skopeo --override-os linux --override-arch amd64 inspect docker://ghcr.io/o/img:1.0.0": {
                "Created": "1970-01-01T00:00:00Z",
                "Digest": "sha256:x",
            },
        }
    )
    with pytest.raises(AnsibleLookupError, match="before 2000"):
        resolve("oci:ghcr.io/o/img", run, days=0)


def test_parse_time_honours_negative_offset():
    assert aged_release._parse_time("2026-09-20T09:00:00-05:00") == datetime(
        2026, 9, 20, 14, 0, tzinfo=UTC
    )


RELEASE = r"^Release (\d+\.\d+\.\d+)"


def commits_run(messages):
    """Answer a 100-commit page, below the newest aged push, newest first."""
    return FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            ACTIVITY.format("master"): [[push("fresh", 1), push("pushed", 5)]],
            "gh api repos/o/r/commits?sha=pushed&per_page=100": [
                {"sha": sha, "commit": {"message": message}}
                for sha, message in messages
            ],
        }
    )


def test_commit_message_selects_newest_matching_release():
    run = commits_run(
        [
            ("a", "Fix typo"),
            ("b", "Release 1.9.0 (#115)\n\nbody"),
            ("c", "Release 1.8.4 (#114)"),
        ]
    )
    assert resolve("github-commit:o/r", run, message=RELEASE) == {
        "version": "1.9.0",
        "commit": "b",
    }


def test_commit_message_matches_only_the_subject_line():
    run = commits_run([("a", "Merge branch x\n\nRelease 2.0.0")])
    with pytest.raises(AnsibleLookupError, match="no commit"):
        resolve("github-commit:o/r", run, message=RELEASE)


def test_commit_message_without_match_raises():
    run = commits_run([("a", "Fix typo")])
    with pytest.raises(AnsibleLookupError, match="no commit"):
        resolve("github-commit:o/r", run, message=RELEASE)


def test_commit_message_is_part_of_the_cache_key(monkeypatch, tmp_path):
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "main"},
            ACTIVITY.format("main"): [[push("head", 5, ref="refs/heads/main")]],
            "gh api repos/o/r/commits?sha=head&per_page=100": [
                {"sha": "head", "commit": {"message": "Fix typo"}},
                {"sha": "rel", "commit": {"message": "Release 1.0.0"}},
            ],
        }
    )
    monkeypatch.setattr(aged_release, "_run", run)
    monkeypatch.setattr(aged_release, "_now", lambda: NOW)
    monkeypatch.setattr(aged_release, "_cache_path", lambda: tmp_path / "cache.json")
    aged_release._CACHE.clear()
    lookup = aged_release.LookupModule()
    variables = {"supply_chain_cooldown_days": 4}
    assert lookup.run(["github-commit:o/r"], variables) == [{"commit": "head"}]
    assert lookup.run(["github-commit:o/r"], variables, message=RELEASE) == [
        {"version": "1.0.0", "commit": "rel"}
    ]
