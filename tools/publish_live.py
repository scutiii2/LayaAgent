"""Publish the deployment-only files of a source ref to the `live` branch.

Builds a commit from the paths in DEPLOY_PATHS using a temporary git index, so
your working tree, index and current branch are never touched. The commit's
parent is the remote `live` tip, so the push is a normal fast-forward.

    python tools/publish_live.py              # publish main
    python tools/publish_live.py --dry-run    # show what would be published
    python tools/publish_live.py --source HEAD
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Everything the image builds from and the compose/nginx files that run it. Add a path here when a service is added.
DEPLOY_PATHS = [
    "Dockerfile",
    "docker-compose.yml",
    "nginx.conf",
    "pyproject.toml",
    "src",
    "web",
    "deployment.md",
]
# Left out of live: Python tests/ folders are not built into the image.
EXCLUDE_DIRS = {"tests"}
EXCLUDE_PREFIXES: tuple[str, ...] = ()
BRANCH = "live"
REMOTE = "origin"
ROOT = Path(__file__).resolve().parent.parent


def git(*args: str, env: dict | None = None, stdin: str | None = None) -> str:
    # Bytes in and out: text mode would turn "\n" into "\r\n" on Windows and corrupt the index entries.
    result = subprocess.run(
        ["git", *args], cwd=ROOT, env=env, input=stdin.encode() if stdin else None, capture_output=True
    )
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode(errors="replace").strip()


def remote_live_tip() -> str | None:
    """The remote `live` commit, fetched so its tree can be compared; None if the branch does not exist yet."""
    line = git("ls-remote", "--heads", REMOTE, f"refs/heads/{BRANCH}")
    if not line:
        return None
    tip = line.split()[0]
    git("fetch", "--quiet", REMOTE, f"refs/heads/{BRANCH}")
    return tip


def build_tree(source: str) -> str:
    """Write a tree holding only DEPLOY_PATHS from `source`, using a throwaway index."""
    kept = [
        line
        for line in git("ls-tree", "-r", source, "--", *DEPLOY_PATHS).splitlines()
        if not (
            line.split("\t", 1)[1].startswith(EXCLUDE_PREFIXES)
            or EXCLUDE_DIRS.intersection(line.split("\t", 1)[1].split("/")[:-1])
        )
    ]
    listing = "\n".join(kept)
    if not listing:
        sys.exit(f"None of the deploy paths exist in {source}.")
    present = {line.split("\t", 1)[1] for line in listing.splitlines()}
    for path in DEPLOY_PATHS:
        if not any(p == path or p.startswith(path + "/") for p in present):
            print(f"warning: {path} not found in {source}", file=sys.stderr)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git("update-index", "--add", "--index-info", env=env, stdin=listing + "\n")
        return git("write-tree", env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="main", help="ref to publish from (default: main)")
    parser.add_argument("--dry-run", action="store_true", help="build and report, push nothing")
    args = parser.parse_args()

    source_sha = git("rev-parse", "--verify", f"{args.source}^{{commit}}")
    tree = build_tree(source_sha)
    count = len(git("ls-tree", "-r", "--name-only", tree).splitlines())
    parent = remote_live_tip()
    parent_tree = git("rev-parse", f"{parent}^{{tree}}") if parent else None

    print(f"source {args.source} ({source_sha[:8]}) -> {count} files, tree {tree[:8]}")
    if tree == parent_tree:
        print(f"{BRANCH} is already up to date.")
        return

    subject = git("log", "-1", "--format=%s", source_sha)
    message = f"live: {source_sha[:8]} {subject}"
    if args.dry_run:
        print(f"dry run: would commit '{message}' on top of {parent[:8] if parent else 'nothing (new branch)'}")
        return

    commit = git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", message)
    git("push", REMOTE, f"{commit}:refs/heads/{BRANCH}")
    print(f"pushed {commit[:8]} to {REMOTE}/{BRANCH}")


if __name__ == "__main__":
    main()
