"""Keep sync state on a separate GitHub branch using the Contents API."""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import requests

BRANCH = "sync-state"
STATE_PATH = "data/state.json"

class GitHubState:
    def __init__(self, repo: str, token: str, commit: str, api_url: str = "https://api.github.com",
                 state_path: Path = Path(STATE_PATH), session: requests.Session | None = None) -> None:
        if not repo or "/" not in repo or not token:
            raise ValueError("GITHUB_REPOSITORY and GITHUB_TOKEN are required.")
        self.repo, self.token, self.commit = repo, token, commit
        self.api_url = api_url.rstrip("/")
        self.path = state_path
        self.session = session or requests.Session()

    def _request(self, method: str, endpoint: str, *, not_found_ok: bool = False, **kwargs):
        response = self.session.request(
            method, f"{self.api_url}/repos/{self.repo}/{endpoint}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"}, timeout=25, **kwargs
        )
        if response.status_code == 404 and not_found_ok:
            return None
        response.raise_for_status()
        return response.json()

    def _remote_state(self):
        return self._request("GET", f"contents/{STATE_PATH}", not_found_ok=True,
                             params={"ref": BRANCH})

    @staticmethod
    def _decode(content: str) -> bytes:
        raw = base64.b64decode(content, validate=False)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("accounts"), dict):
            raise ValueError("Remote state is invalid; refusing to replace local state.")
        return raw

    def restore(self) -> bool:
        existing = self._remote_state()
        if existing is None:
            print("No sync-state data yet; using initial local state.")
            return False
        decoded = self._decode(existing["content"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_bytes(decoded)
        os.replace(tmp, self.path)
        print("Restored state from sync-state branch.")
        return True

    def persist(self) -> bool:
        if not self.path.is_file():
            print("No state to persist.")
            return False
        local = self.path.read_bytes()
        self._decode(base64.b64encode(local).decode("ascii"))
        branch_ref = self._request("GET", f"git/ref/heads/{BRANCH}", not_found_ok=True)
        if branch_ref is None:
            if not self.commit:
                raise ValueError("GITHUB_SHA is required to initialize the state branch.")
            try:
                self._request("POST", "git/refs",
                              json={"ref": f"refs/heads/{BRANCH}", "sha": self.commit})
                print("Created sync-state branch.")
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 422:
                    raise
                if self._request("GET", f"git/ref/heads/{BRANCH}", not_found_ok=True) is None:
                    raise
        existing = self._remote_state()
        if existing is not None and self._decode(existing["content"]) == local:
            print("Sync state unchanged.")
            return False
        payload = {"message": "Update sync state", "branch": BRANCH,
                   "content": base64.b64encode(local).decode("ascii")}
        if existing is not None:
            payload["sha"] = existing["sha"]
        self._request("PUT", f"contents/{STATE_PATH}", json=payload)
        print("Saved state to sync-state branch.")
        return True

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["restore", "persist"])
    args = parser.parse_args()
    client = GitHubState(
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_TOKEN", ""),
        os.environ.get("GITHUB_SHA", ""),
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    getattr(client, args.action)()

if __name__ == "__main__":
    main()
