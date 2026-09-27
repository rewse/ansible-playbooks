"""Resolve the newest release that has survived the supply-chain cooldown."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ansible.errors import AnsibleLookupError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

DOCUMENTATION = r"""
name: aged_release
short_description: Resolve the newest release older than the supply-chain cooldown
description:
  - Returns the newest version of a container image, GitHub release, GitHub tag,
    or default-branch commit that was published at least O(days) days ago.
  - The result is pinned by content (image digest, asset sha256, or commit SHA)
    so a later re-push under the same name is not adopted.
  - Runs on the controller with C(skopeo) and C(gh).
options:
  _terms:
    description: One source, prefixed with oci:, github-release:, github-tag:, or github-commit:.
    required: true
  pattern:
    description: Regular expression a tag must match.
    default: '^v?\d+(\.\d+)+$'
  days:
    description: Minimum age in days. Defaults to supply_chain_cooldown_days.
    type: int
  platform:
    description: Image platform for oci:, such as linux/arm64.
  asset:
    description: Release asset name for github-release:; {version} expands to the tag.
"""

RETURN = r"""
_raw:
  description: A dictionary per term; keys depend on the source type.
  type: list
  elements: dict
"""

DEFAULT_PATTERN = r"^v?\d+(\.\d+)+$"

_CACHE: dict[tuple, dict] = {}
# Entries older than this are ignored, so a reused process group id cannot
# serve a result from an earlier run.
_CACHE_TTL = timedelta(hours=12)
_display = Display()


def _run(cmd: list[str]) -> str:
    """Run a command and return stdout; raise with stderr on failure."""
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(f"{cmd[0]} is not installed on the controller")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"{cmd[0]} exited {proc.returncode}")
    return proc.stdout


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp; skopeo reports nanoseconds, so keep seconds."""
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def version_key(tag: str) -> list[int]:
    """Order tags by their numeric components, e.g. 2025.10.1 > 2025.6.9."""
    return [int(n) for n in re.findall(r"\d+", tag)]


def ordered(versions: list[str], pattern: str) -> list[str]:
    """Keep versions matching the pattern, newest first."""
    regex = re.compile(pattern)
    return sorted(
        (v for v in versions if regex.search(v)), key=version_key, reverse=True
    )


def select(candidates: list[dict], pattern: str, days: int, now: datetime) -> dict:
    """Return the newest candidate matching the pattern and at least days old."""
    by_version = {c["version"]: c for c in candidates}
    for version in ordered(list(by_version), pattern):
        if now - by_version[version]["published"] >= timedelta(days=days):
            return by_version[version]
    raise AnsibleLookupError(
        f"no version matching {pattern} is at least {days} day(s) old"
    )


def _json(run: Callable[[list[str]], str], cmd: list[str]):
    return json.loads(run(cmd))


def _oci(repo, pattern, days, platform, run, now):
    os_name, _, arch = (platform or "linux/amd64").partition("/")
    tags = _json(run, ["skopeo", "list-tags", f"docker://{repo}"])["Tags"]
    for tag in ordered(tags, pattern):
        # Inspecting is one request per tag, so stop at the first aged tag.
        meta = _json(
            run,
            [
                "skopeo",
                "--override-os",
                os_name,
                "--override-arch",
                arch,
                "inspect",
                f"docker://{repo}:{tag}",
            ],
        )
        if now - _parse_time(meta["Created"]) >= timedelta(days=days):
            return {"version": tag, "ref": f"{repo}:{tag}@{meta['Digest']}"}
    raise AnsibleLookupError(
        f"no tag of {repo} matching {pattern} is at least {days} day(s) old"
    )


def _release(repo, pattern, days, asset, run, now):
    releases = _json(run, ["gh", "api", f"repos/{repo}/releases?per_page=100"])
    candidates = [
        {
            "version": r["tag_name"],
            "published": _parse_time(r["published_at"]),
            "assets": r["assets"],
        }
        for r in releases
        if not r["draft"] and not r["prerelease"] and r.get("published_at")
    ]
    chosen = select(candidates, pattern, days, now)
    if asset is None:
        return {"version": chosen["version"], "url": "", "checksum": ""}
    name = asset.replace("{version}", chosen["version"].lstrip("v"))
    for item in chosen["assets"]:
        if item["name"] in (name, asset.replace("{version}", chosen["version"])):
            checksum = item.get("digest") or ""
            if not checksum:
                _display.vvv(
                    f"aged_release: {repo} {chosen['version']} {item['name']} has no digest"
                )
            return {
                "version": chosen["version"],
                "url": item["browser_download_url"],
                "checksum": checksum,
            }
    raise AnsibleLookupError(f"{repo} {chosen['version']} has no asset named {name}")


def _tag(repo, pattern, days, run, now):
    tags = _json(run, ["gh", "api", f"repos/{repo}/tags?per_page=100"])
    shas = {t["name"]: t["commit"]["sha"] for t in tags}
    for name in ordered(list(shas), pattern):
        commit = _json(run, ["gh", "api", f"repos/{repo}/commits/{shas[name]}"])
        if now - _parse_time(commit["commit"]["committer"]["date"]) >= timedelta(
            days=days
        ):
            return {"version": name, "commit": shas[name]}
    raise AnsibleLookupError(
        f"no tag of {repo} matching {pattern} is at least {days} day(s) old"
    )


def _commit(repo, days, run, now):
    branch = _json(run, ["gh", "api", f"repos/{repo}"])["default_branch"]
    until = _iso(now - timedelta(days=days))
    commits = _json(
        run,
        ["gh", "api", f"repos/{repo}/commits?sha={branch}&until={until}&per_page=1"],
    )
    if not commits:
        raise AnsibleLookupError(
            f"{repo} has no commit on {branch} at least {days} day(s) old"
        )
    return {"commit": commits[0]["sha"]}


def resolve(
    term: str,
    *,
    pattern: str,
    days: int,
    platform: str | None,
    asset: str | None,
    run: Callable[[list[str]], str],
    now: datetime,
) -> dict:
    kind, sep, source = term.partition(":")
    if not sep or not source:
        raise AnsibleLookupError(f"aged_release: malformed term {term!r}")
    try:
        if kind == "oci":
            return _oci(source, pattern, days, platform, run, now)
        if kind == "github-release":
            return _release(source, pattern, days, asset, run, now)
        if kind == "github-tag":
            return _tag(source, pattern, days, run, now)
        if kind == "github-commit":
            return _commit(source, days, run, now)
    except AnsibleLookupError:
        raise
    except Exception as exc:
        raise AnsibleLookupError(f"aged_release: {term}: {exc}") from exc
    raise AnsibleLookupError(f"aged_release: unknown source type {kind!r}")


def _cache_path() -> Path:
    """One file per ansible-playbook run.

    Ansible templates each task in a worker forked per host, so a module-level
    cache dies with the worker. The workers share the playbook's process group,
    which keys a file every host and task of the run can read.
    """
    return (
        Path(tempfile.gettempdir()) / f"aged_release-{os.getuid()}-{os.getpgrp()}.json"
    )


def _cached(key: tuple, compute: Callable[[], dict]) -> dict:
    if key in _CACHE:
        return _CACHE[key]
    path = _cache_path()
    name = json.dumps(key)
    with open(path, "a+", encoding="utf-8") as handle:
        # Held across the resolution so parallel hosts resolve a term once.
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            data = json.loads(handle.read() or "{}")
        except json.JSONDecodeError:
            data = {}
        entry = data.get(name)
        if entry and _now() - datetime.fromisoformat(entry["at"]) < _CACHE_TTL:
            result = entry["value"]
        else:
            result = compute()
            data[name] = {"at": _now().isoformat(), "value": result}
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(data))
    _CACHE[key] = result
    return result


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        variables = variables or {}
        pattern = kwargs.get("pattern", DEFAULT_PATTERN)
        days = kwargs.get("days")
        if days is None:
            days = variables.get("supply_chain_cooldown_days")
        if days is None:
            raise AnsibleLookupError(
                "aged_release: days is not set and supply_chain_cooldown_days is undefined"
            )
        days = int(days)
        platform = kwargs.get("platform")
        asset = kwargs.get("asset")
        results = []
        for term in terms:
            key = (term, pattern, days, platform, asset)
            results.append(
                _cached(
                    key,
                    lambda term=term: resolve(
                        term,
                        pattern=pattern,
                        days=days,
                        platform=platform,
                        asset=asset,
                        run=_run,
                        now=_now(),
                    ),
                )
            )
        return results
