import base64
import json

import pytest

from insta_tg_sync.github_state import GitHubState

STATE = b'{"accounts": {}, "usage": {"2026-10-26": {"apify": 351}}}\n'


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakeSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.replies.pop(0)


def client(tmp_path, replies):
    return GitHubState("owner/repo", "test-token", "abc123",
                       state_path=tmp_path / "data/state.json",
                       session=FakeSession(replies))


def remote(content=STATE, sha="original-sha"):
    return Response(payload={"sha": sha, "content": base64.b64encode(content).decode()})


def test_restore_not_found_preserves_existing_local_state(tmp_path):
    c = client(tmp_path, [Response(404)])
    c.path.parent.mkdir(parents=True)
    c.path.write_bytes(STATE)
    assert c.restore() is False
    assert c.path.read_bytes() == STATE


def test_restore_reads_branch_without_touching_git_history(tmp_path):
    c = client(tmp_path, [remote()])
    assert c.restore() is True
    assert c.path.read_bytes() == STATE
    assert c.session.calls[0][2]["params"] == {"ref": "sync-state"}


def test_restore_invalid_state_does_not_overwrite_local(tmp_path):
    c = client(tmp_path, [remote(b'{"oops": true}')])
    c.path.parent.mkdir(parents=True)
    c.path.write_bytes(STATE)
    with pytest.raises(ValueError):
        c.restore()
    assert c.path.read_bytes() == STATE


def test_persist_creates_missing_branch_and_publishes_state(tmp_path):
    c = client(tmp_path, [Response(404), Response(payload={}), Response(404), Response(payload={})])
    c.path.parent.mkdir(parents=True)
    c.path.write_bytes(STATE)
    assert c.persist() is True
    methods = [method for method, _, _ in c.session.calls]
    assert methods == ["GET", "POST", "GET", "PUT"]
    assert c.session.calls[1][2]["json"] == {"ref": "refs/heads/sync-state", "sha": "abc123"}
    published = c.session.calls[3][2]["json"]
    assert base64.b64decode(published["content"]) == STATE
    assert published["branch"] == "sync-state"


def test_persist_skips_identical_state(tmp_path):
    c = client(tmp_path, [Response(payload={"ref": "heads/sync-state"}), remote()])
    c.path.parent.mkdir(parents=True)
    c.path.write_bytes(STATE)
    assert c.persist() is False
    assert len(c.session.calls) == 2


def test_persist_uses_blob_sha_when_updating(tmp_path):
    c = client(tmp_path, [Response(payload={"ref": "heads/sync-state"}),
                          remote(b'{"accounts":{}}', "abc-sha"), Response(payload={})])
    c.path.parent.mkdir(parents=True)
    c.path.write_bytes(STATE)
    assert c.persist() is True
    assert c.session.calls[-1][2]["json"]["sha"] == "abc-sha"
