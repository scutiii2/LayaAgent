import json
import time
from concurrent.futures import ThreadPoolExecutor

from tokens import TokenStore


def test_new_token_has_null_last_used(tmp_path):
    store = TokenStore(tmp_path / "tokens.json")
    made = store.create("project")
    assert made["last_used"] is None
    assert store.list() == [{"id": made["id"], "name": "project", "created": made["created"], "last_used": None}]


def test_authenticated_use_is_persisted_and_writes_are_throttled(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"
    store = TokenStore(path)
    first = store.create("first")["token"]
    second = store.create("second")["token"]
    monkeypatch.setattr("tokens.time.time", lambda: 1000)
    assert not store.valid("wrong")
    assert all(row["last_used"] is None for row in store.list())
    assert store.valid(first)
    assert json.loads(path.read_text())[0]["last_used"] == 1000
    # A different replica sees the persisted timestamp and also skips writing.
    replica = TokenStore(path)
    monkeypatch.setattr("tokens.time.time", lambda: 1059)
    before = path.stat().st_mtime_ns
    assert replica.valid(first)
    assert path.stat().st_mtime_ns == before
    assert store.valid(second)
    assert json.loads(path.read_text())[1]["last_used"] == 1059
    monkeypatch.setattr("tokens.time.time", lambda: 1060)
    assert store.valid(first)
    assert json.loads(path.read_text())[0]["last_used"] == 1060


def test_old_token_file_loads_and_tracks_next_use(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"
    store = TokenStore(path)
    made = store.create("legacy")
    rows = json.loads(path.read_text())
    rows[0].pop("last_used", None)
    path.write_text(json.dumps(rows))
    reloaded = TokenStore(path)
    assert reloaded.list()[0]["last_used"] is None
    monkeypatch.setattr("tokens.time.time", lambda: 2000)
    assert reloaded.valid(made["token"])
    assert reloaded.list()[0]["last_used"] == 2000


def test_simultaneous_authentication_writes_once(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"
    token = TokenStore(path).create("busy")["token"]
    writes = []
    save = TokenStore._save

    def slow_save(self, rows):
        writes.append(1)
        time.sleep(0.03)
        save(self, rows)

    monkeypatch.setattr(TokenStore, "_save", slow_save)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda _: TokenStore(path).valid(token), range(4)))
    assert len(writes) == 1
