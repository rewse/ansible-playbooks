"""Resolve the newest release that has survived the supply-chain cooldown."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path

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
  - Ages come from times the hosting service records, never from the image
    Created field or a committer date, which the publisher sets. An image is
    aged by its Docker Hub tag push time or its GitHub package version
    creation time, a commit by the push that put it on the default branch,
    and a release asset by the later of its release publication and its last
    upload. When no such time is available the lookup fails rather than fall
    back to a publisher's date.
  - A tag needs a release published at least O(days) days ago, and its
    current commit must already have been on the default branch O(days) days
    ago. GitHub records no time for creating, moving, or renaming a tag, so
    the release alone does not date the commit the tag points at now.
  - A ghcr.io package version keeps its creation time when a tag is added to
    it, so an older image newly given a matching tag is aged from its build.
  - With O(days=0), for sources this account owns, the newest version is taken
    without asking for those times.
  - Runs on the controller with C(skopeo) and C(gh). Ageing a ghcr.io image
    needs the read:packages scope on the gh token.
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
  message:
    description:
      - Regular expression for github-commit: that the commit subject must match.
      - The newest aged commit whose subject matches is returned, with the first
        group as its version.
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


def _fetch(url: str) -> str:
    """GET an HTTPS URL and return the body; raise on an HTTP error."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing to fetch {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "aged_release"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp into UTC.

    skopeo reports nanoseconds, which fromisoformat rejects, so the fraction is
    cut to microseconds. A timestamp without an offset is taken as UTC.
    """
    text = value.strip().replace("Z", "+00:00")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?([+-]\d{2}:\d{2})?", text
    )
    if not match:
        raise ValueError(f"unrecognised timestamp {value!r}")
    base, fraction, offset = match.groups()
    iso = (
        base
        + (f".{fraction[:6].ljust(6, '0')}" if fraction else "")
        + (offset or "+00:00")
    )
    return datetime.fromisoformat(iso).astimezone(UTC)


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


def _pages(run: Callable[[list[str]], str], path: str) -> list:
    """Read every page of a GitHub list endpoint as one flat list."""
    return [
        item
        for page in _json(run, ["gh", "api", "--paginate", "--slurp", path])
        for item in page
    ]


# A reproducible build sets Created to the epoch or year 1, which would make
# every tag look old enough and silently skip the cooldown.
_EARLIEST_CREATED = datetime(2000, 1, 1, tzinfo=UTC)

_DOCKER_HUB = ("docker.io", "index.docker.io", "registry-1.docker.io")
_READ_PACKAGES_HINT = "gh auth refresh -s read:packages"


def _registry(repo: str) -> tuple[str, str]:
    """Split an image name into its registry and the path within it."""
    first, sep, rest = repo.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first, rest
    return "docker.io", repo


def _docker_hub_pushed(path, fetch):
    """Return a function giving the Docker Hub push time of a tag at a digest."""
    namespace, _, name = path.rpartition("/")
    # Official images live in the library namespace.
    namespace = namespace or "library"

    def pushed(tag, digest):
        data = json.loads(
            fetch(
                f"https://hub.docker.com/v2/namespaces/{namespace}"
                f"/repositories/{name}/tags/{tag}"
            )
        )
        if not data.get("tag_last_pushed"):
            raise AnsibleLookupError(
                f"Docker Hub reports no push time for {namespace}/{name}:{tag}"
            )
        if data.get("digest") != digest:
            # The push time belongs to another digest, so it does not date the
            # one that would be pinned.
            _display.vvv(
                f"aged_release: {namespace}/{name}:{tag} is {data.get('digest')} "
                f"on Docker Hub but {digest} in the registry"
            )
            return None
        return _parse_time(data["tag_last_pushed"])

    return pushed


def _ghcr_pushed(path, run):
    """Return a function giving the GitHub creation time of a package digest."""
    owner, _, name = path.partition("/")
    kind = (
        "orgs"
        if _json(run, ["gh", "api", f"users/{owner}"]).get("type") == "Organization"
        else "users"
    )
    base = (
        f"{kind}/{owner}/packages/container/{urllib.parse.quote(name, safe='')}"
        "/versions?per_page=100"
    )
    created: dict[str, str | None] = {}
    page = 0
    exhausted = False

    def pushed(tag, digest):
        nonlocal page, exhausted
        # Versions are listed newest first, so recent tags need few pages.
        while digest not in created and not exhausted:
            page += 1
            try:
                versions = _json(run, ["gh", "api", f"{base}&page={page}"])
            except RuntimeError as exc:
                if "HTTP 403" in str(exc) or "HTTP 404" in str(exc):
                    raise AnsibleLookupError(
                        f"cannot read the package versions of ghcr.io/{path}; give "
                        "the controller's gh token the read:packages scope with "
                        f"`{_READ_PACKAGES_HINT}`"
                    ) from exc
                raise
            for item in versions:
                created[item["name"]] = item.get("created_at")
            exhausted = len(versions) < 100
        if not created.get(digest):
            raise AnsibleLookupError(
                f"GitHub lists no creation time for ghcr.io/{path}:{tag} at {digest}"
            )
        return _parse_time(str(created[digest]))

    return pushed


def _push_times(repo, run, fetch):
    registry, path = _registry(repo)
    if registry in _DOCKER_HUB:
        return _docker_hub_pushed(path, fetch)
    if registry == "ghcr.io":
        return _ghcr_pushed(path, run)
    raise AnsibleLookupError(
        f"{repo}: {registry} offers no push time to age images by; "
        "only Docker Hub and ghcr.io images can have a cooldown"
    )


def _oci(repo, pattern, days, platform, run, fetch, now):
    os_name, _, arch = (platform or "linux/amd64").partition("/")
    tags = _json(run, ["skopeo", "list-tags", f"docker://{repo}"])["Tags"]
    pushed = None if days == 0 else _push_times(repo, run, fetch)
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
        if pushed is None:
            created = _parse_time(meta["Created"])
            if created < _EARLIEST_CREATED:
                raise AnsibleLookupError(
                    f"{repo}:{tag} Created {meta['Created']} is before 2000"
                )
        else:
            created = pushed(tag, meta["Digest"])
            if created is None:
                continue
        if now - created >= timedelta(days=days):
            return {"version": tag, "ref": f"{repo}:{tag}@{meta['Digest']}"}
    raise AnsibleLookupError(
        f"no tag of {repo} matching {pattern} is at least {days} day(s) old"
    )


def _find_asset(assets, asset, version):
    """Return the asset whose name matches, with {version} with or without v."""
    names = (
        asset.replace("{version}", version.lstrip("v")),
        asset.replace("{version}", version),
    )
    return next((item for item in assets if item["name"] in names), None)


def _release(repo, pattern, days, asset, run, now):
    releases = _pages(run, f"repos/{repo}/releases?per_page=100")
    candidates = []
    for r in releases:
        if r["draft"] or r["prerelease"] or not r.get("published_at"):
            continue
        published = _parse_time(r["published_at"])
        item = None if asset is None else _find_asset(r["assets"], asset, r["tag_name"])
        if item is not None:
            # An asset can be uploaded again after its release is published.
            if not item.get("updated_at"):
                raise AnsibleLookupError(
                    f"{repo} {r['tag_name']} {item['name']} has no upload time"
                )
            published = max(published, _parse_time(item["updated_at"]))
        candidates.append(
            {"version": r["tag_name"], "published": published, "asset": item}
        )
    try:
        chosen = select(candidates, pattern, days, now)
    except AnsibleLookupError as exc:
        raise AnsibleLookupError(f"{repo}: {exc}") from exc
    if asset is None:
        return {"version": chosen["version"], "url": "", "checksum": ""}
    item = chosen["asset"]
    if item is None:
        name = asset.replace("{version}", chosen["version"].lstrip("v"))
        raise AnsibleLookupError(
            f"{repo} {chosen['version']} has no asset named {name}"
        )
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


def _on_branch(repo, sha, head, run):
    """Return whether sha is head or one of its ancestors."""
    try:
        status = _json(
            run,
            [
                "gh",
                "api",
                f"repos/{repo}/compare/{sha}...{head}?per_page=1",
                "--jq",
                "{status}",
            ],
        )["status"]
    except RuntimeError as exc:
        # GitHub answers 404 when the two commits share no history.
        if "HTTP 404" in str(exc):
            return False
        raise
    return status in ("ahead", "identical")


def _tag(repo, pattern, days, run, now):
    tags = _pages(run, f"repos/{repo}/tags?per_page=100")
    shas = {t["name"]: t["commit"]["sha"] for t in tags}
    names = ordered(list(shas), pattern)
    if days == 0:
        for name in names:
            commit = _json(run, ["gh", "api", f"repos/{repo}/commits/{shas[name]}"])
            if _parse_time(commit["commit"]["committer"]["date"]) <= now:
                return {"version": name, "commit": shas[name]}
    else:
        chosen = _aged_tag(repo, names, shas, days, run, now)
        if chosen is not None:
            return {"version": chosen, "commit": shas[chosen]}
    raise AnsibleLookupError(
        f"no tag of {repo} matching {pattern} is at least {days} day(s) old"
    )


def _aged_tag(repo, names, shas, days, run, now):
    """Return the newest tag whose release and commit are both days old."""
    published = {
        r["tag_name"]: _parse_time(r["published_at"])
        for r in _pages(run, f"repos/{repo}/releases?per_page=100")
        if not r["draft"] and r.get("published_at")
    }
    branch = head = None
    for name in names:
        if name not in published:
            # Without a release GitHub records no time to age the tag by, so
            # it is never taken; an older tag with a release may still be.
            _display.vvv(f"aged_release: {repo} tag {name} has no published release")
            continue
        if now - published[name] < timedelta(days=days):
            continue
        if head is None:
            branch = _json(run, ["gh", "api", f"repos/{repo}"])["default_branch"]
            head = _pushed_head(repo, branch, days, run, now)
        # The release dates the tag name only; a tag can be moved, or an old
        # release renamed, onto a commit pushed a minute ago.
        if _on_branch(repo, shas[name], head, run):
            return name
        _display.vvv(
            f"aged_release: {repo} tag {name} is at {shas[name]}, which {branch} "
            f"did not hold {days} day(s) ago"
        )
    return None


_NULL_SHA = "0" * 40


def _pushed_head(repo, branch, days, run, now):
    """Return the branch head left by the newest push at least days old."""
    ref = f"refs/heads/{branch}"
    cutoff = now - timedelta(days=days)
    # Merges through the web interface are recorded as pr_merge or
    # merge_queue_merge rather than push, so every activity that leaves the
    # branch at a commit counts.
    activities = sorted(
        (
            a
            for a in _pages(run, f"repos/{repo}/activity?ref={ref}&per_page=100")
            if a.get("ref") == ref
            and a["activity_type"] != "branch_deletion"
            and a.get("after")
            and a["after"] != _NULL_SHA
        ),
        key=lambda a: _parse_time(a["timestamp"]),
        reverse=True,
    )
    for activity in activities:
        if _parse_time(activity["timestamp"]) <= cutoff:
            return activity["after"]
    raise AnsibleLookupError(
        f"{repo} has no push to {branch} at least {days} day(s) old"
    )


def _commit(repo, days, run, now, message=None):
    branch = _json(run, ["gh", "api", f"repos/{repo}"])["default_branch"]
    if days == 0:
        query = f"sha={branch}&until={_iso(now)}"
    else:
        head = _pushed_head(repo, branch, days, run, now)
        if message is None:
            return {"commit": head}
        query = f"sha={head}"
    if message is None:
        commits = _json(run, ["gh", "api", f"repos/{repo}/commits?{query}&per_page=1"])
        if not commits:
            raise AnsibleLookupError(
                f"{repo} has no commit on {branch} at least {days} day(s) old"
            )
        return {"commit": commits[0]["sha"]}
    # One page: a project that marks releases with a commit subject releases far
    # more often than once per 100 commits.
    commits = _json(run, ["gh", "api", f"repos/{repo}/commits?{query}&per_page=100"])
    regex = re.compile(message)
    for commit in commits:
        match = regex.search(commit["commit"]["message"].split("\n", 1)[0])
        if match:
            return {"version": match.group(1), "commit": commit["sha"]}
    raise AnsibleLookupError(
        f"no commit of {repo} on {branch} matching {message} is at least {days} day(s) old"
    )


def resolve(
    term: str,
    *,
    pattern: str,
    days: int,
    platform: str | None,
    asset: str | None,
    run: Callable[[list[str]], str],
    fetch: Callable[[str], str],
    now: datetime,
    message: str | None = None,
) -> dict:
    kind, sep, source = term.partition(":")
    if not sep or not source:
        raise AnsibleLookupError(f"aged_release: malformed term {term!r}")
    try:
        if kind == "oci":
            return _oci(source, pattern, days, platform, run, fetch, now)
        if kind == "github-release":
            return _release(source, pattern, days, asset, run, now)
        if kind == "github-tag":
            return _tag(source, pattern, days, run, now)
        if kind == "github-commit":
            return _commit(source, days, run, now, message)
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
    def run(self, terms, variables=None, **kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]  ansible-core leaves LookupBase.run unannotated, so its return type is inferred as None
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
        message = kwargs.get("message")
        results = []
        for term in terms:
            key = (term, pattern, days, platform, asset, message)
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
                        fetch=_fetch,
                        now=_now(),
                        message=message,
                    ),
                )
            )
        return results
