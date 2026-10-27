"""Settings changed on the admin page, kept in a JSON file beside the tokens so they survive a restart.

shortcut: read once at start, so replicas sharing the file pick a change up when they restart; upgrade to
reading per request if live sync across replicas matters."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load(path: str | os.PathLike[str]) -> dict:
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save(path: str | os.PathLike[str], **values: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({**load(path), **values}, indent=2), "utf-8")
    os.replace(temp, path)
