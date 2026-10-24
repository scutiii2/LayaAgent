#!/usr/bin/env python3
"""Zip up this repo, excluding everything covered by .gitignore.

Uses `git ls-files` to determine which files to include, so all
.gitignore rules (including nested ones and negation patterns) are
honored automatically. Output goes to zip_versions/, which is itself
gitignored.
"""

import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "zip_versions"


def get_included_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return [line for line in result.stdout.splitlines() if line]


def main() -> None:
    files = get_included_files()
    if not files:
        print("No files found to zip.", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = OUTPUT_DIR / f"{ROOT.name}_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files:
            full_path = ROOT / rel_path
            if full_path.is_file():
                zf.write(full_path, rel_path)

    print(f"Created {zip_path} ({len(files)} files)")


if __name__ == "__main__":
    main()
