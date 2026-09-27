"""Tests for the aged_release lookup plugin."""

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from ansible.errors import AnsibleLookupError

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[1] / "plugins" / "lookup")
)

import aged_release  # noqa: E402

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def ago(days):
    return NOW - timedelta(days=days)


def iso(value):
    """Format a datetime, or a number of days before NOW, as RFC 3339."""
    dt = ago(value) if isinstance(value, int) else value
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeRun:
    """Answer commands from a table keyed by the joined argument list."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, cmd):
        key = " ".join(cmd)
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
    return aged_release.resolve(term, run=run, now=NOW, **kwargs)


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
        }
    )
    result = resolve("oci:ghcr.io/o/img", run, platform="linux/arm64")
    assert result == {"version": "1.0.0", "ref": "ghcr.io/o/img:1.0.0@sha256:old"}


def test_release_skips_draft_and_prerelease():
    run = FakeRun(
        {
            "gh api repos/o/r/releases?per_page=100": [
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
                            "digest": "sha256:aa",
                        }
                    ],
                },
            ]
        }
    )
    assert resolve("github-release:o/r", run, asset="a.js")["version"] == "v1.0.0"


def test_release_asset_checksum():
    run = FakeRun(
        {
            "gh api repos/o/r/releases?per_page=100": [
                {
                    "tag_name": "v0.2.0",
                    "draft": False,
                    "prerelease": False,
                    "published_at": iso(10),
                    "assets": [
                        {
                            "name": "tool_0.2.0_linux_arm64.bz2",
                            "browser_download_url": "https://x/t.bz2",
                            "digest": "sha256:bb",
                        },
                        {
                            "name": "tool_0.2.0_linux_amd64.bz2",
                            "browser_download_url": "https://x/u.bz2",
                            "digest": "sha256:cc",
                        },
                    ],
                },
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
            "gh api repos/o/r/releases?per_page=100": [
                {
                    "tag_name": "1.0.0",
                    "draft": False,
                    "prerelease": False,
                    "published_at": iso(10),
                    "assets": [
                        {
                            "name": "a.js",
                            "browser_download_url": "https://x/a.js",
                            "digest": None,
                        }
                    ],
                },
            ]
        }
    )
    assert resolve("github-release:o/r", run, asset="a.js")["checksum"] == ""


def test_tag_returns_commit_sha():
    run = FakeRun(
        {
            "gh api repos/o/r/tags?per_page=100": [
                {"name": "v1.1.0", "commit": {"sha": "s11"}},
                {"name": "v1.0.0", "commit": {"sha": "s10"}},
            ],
            "gh api repos/o/r/commits/s11": {"commit": {"committer": {"date": iso(1)}}},
            "gh api repos/o/r/commits/s10": {
                "commit": {"committer": {"date": iso(30)}}
            },
        }
    )
    assert resolve("github-tag:o/r", run) == {"version": "v1.0.0", "commit": "s10"}


def test_commit_returns_newest_aged():
    until = iso(ago(4))
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "master"},
            f"gh api repos/o/r/commits?sha=master&until={until}&per_page=1": [
                {"sha": "abc"}
            ],
        }
    )
    assert resolve("github-commit:o/r", run) == {"commit": "abc"}


def test_gh_failure_raises():
    run = FakeRun(
        {
            "gh api repos/o/r/tags?per_page=100": RuntimeError(
                "HTTP 403: API rate limit exceeded"
            )
        }
    )
    with pytest.raises(AnsibleLookupError, match="rate limit"):
        resolve("github-tag:o/r", run)


def test_lookup_caches_identical_calls(monkeypatch, tmp_path):
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "main"},
            f"gh api repos/o/r/commits?sha=main&until={iso(ago(4))}&per_page=1": [
                {"sha": "abc"}
            ],
        }
    )
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
    run = FakeRun(
        {
            "gh api repos/o/r/tags?per_page=100": [
                {"name": "14", "commit": {"sha": "old"}},
                {"name": "v4.2.1", "commit": {"sha": "new"}},
            ],
            "gh api repos/o/r/commits/new": {
                "commit": {"committer": {"date": iso(10)}}
            },
        }
    )
    assert resolve("github-tag:o/r", run) == {"version": "v4.2.1", "commit": "new"}


def test_cache_is_shared_across_worker_processes(monkeypatch, tmp_path):
    run = FakeRun(
        {
            "gh api repos/o/r": {"default_branch": "main"},
            f"gh api repos/o/r/commits?sha=main&until={iso(ago(4))}&per_page=1": [
                {"sha": "abc"}
            ],
        }
    )
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
