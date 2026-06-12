#!/usr/bin/env python3
"""Resolve the newest release tag that has survived the quarantine cooldown.

Supply-chain rationale: a compromised image is usually detected and yanked
within days of being published. By never adopting a tag until its image has
been public for at least N days, the deployment always runs a version that
others have already vetted.

The script lists the tags of a repository, keeps those matching a release
pattern, sorts them version-aware (newest first), and returns the first one
whose image was created at least N days ago, together with its digest. Pinning
"tag@digest" also defeats tag mutation: the digest is the one observed after the
cooldown, so a later malicious re-push under the same tag is not picked up.

Run on the target host so the per-architecture digest matches the host that will
pull it.

Output: a single JSON object on stdout.
  resolved true:  {"resolved": true, "ref": "<repo>:<tag>@<digest>", "tag", "digest", "age"}
  resolved false: {"resolved": false, "reason": "<message>"}
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone


def skopeo(*args):
    proc = subprocess.run(["skopeo", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "skopeo failed")
    return proc.stdout


def version_key(tag):
    """Order tags by their numeric components (e.g. 2025.10.1 > 2025.6.9)."""
    return [int(n) for n in re.findall(r"\d+", tag)]


def main():
    repo, pattern, days = sys.argv[1], sys.argv[2], int(sys.argv[3])
    regex = re.compile(pattern)

    tags = json.loads(skopeo("list-tags", f"docker://{repo}"))["Tags"]
    candidates = sorted(
        (t for t in tags if regex.match(t)), key=version_key, reverse=True
    )

    now = datetime.now(timezone.utc)
    for tag in candidates:
        # Docker hosts run linux; force the linux variant so the pinned digest
        # is valid on the host that pulls it (host architecture is kept).
        meta = json.loads(
            skopeo("--override-os", "linux", "inspect", f"docker://{repo}:{tag}")
        )
        created = datetime.strptime(
            meta["Created"][:19], "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=timezone.utc)
        age = (now - created).days
        if age >= days:
            print(json.dumps({
                "resolved": True,
                "ref": f"{repo}:{tag}@{meta['Digest']}",
                "tag": tag,
                "digest": meta["Digest"],
                "age": age,
            }))
            return

    print(json.dumps({
        "resolved": False,
        "reason": f"no tag matching {pattern} is older than {days} day(s)",
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # Report failure as data; let Ansible decide.
        print(json.dumps({"resolved": False, "reason": str(exc)}))
