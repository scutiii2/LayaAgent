"""Per-project API tokens: a JSON file of sha256 hashes, so any replica sharing the file accepts a token at once.

shortcut: read-modify-write without a lock, so two admins creating a token in the same instant can lose one;
upgrade to a database if the service ever has more than one admin."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

PREFIX = "laya_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self.settings_path = self._path.with_name("settings.json")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return []

    def _save(self, rows: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, indent=2), "utf-8")
        os.replace(temp, self._path)

    def list(self) -> list[dict]:
        return [{k: v for k, v in row.items() if k != "hash"} for row in self._load()]

    def create(self, name: str) -> dict:
        """The new token's row plus its plaintext `token`, which is shown this once and never stored."""
        token = PREFIX + secrets.token_urlsafe(32)
        row = {"id": secrets.token_hex(4), "name": name, "created": int(time.time()), "hash": _hash(token)}
        self._save([*self._load(), row])
        return {"id": row["id"], "name": name, "created": row["created"], "token": token}

    def revoke(self, token_id: str) -> bool:
        rows = self._load()
        kept = [row for row in rows if row["id"] != token_id]
        if len(kept) != len(rows):
            self._save(kept)
        return len(kept) != len(rows)

    def valid(self, token: str) -> bool:
        digest = _hash(token)
        return any(secrets.compare_digest(digest, row["hash"]) for row in self._load())
