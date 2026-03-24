"""
Webby — GitHub API client.

Thin wrapper around httpx for the GitHub REST API. Handles authentication,
rate limiting, and provides helpers for common file and PR operations.

Adapted from CAKE OS webby-website-agent — TNC-specific defaults removed.
"""

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 30.0


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _check_rate_limit(resp: httpx.Response) -> None:
    remaining = resp.headers.get("x-ratelimit-remaining")
    if remaining and int(remaining) < 50:
        logger.warning("GitHub API rate limit low: %s remaining", remaining)


def _repo_url(repo: str, path: str = "") -> str:
    return f"{_GITHUB_API}/repos/{repo}/{path.lstrip('/')}"


def list_contents(token: str, repo: str, path: str = "") -> list[dict]:
    """List files/directories at a path in the repo."""
    url = _repo_url(repo, f"contents/{path}")
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    items = resp.json()
    if isinstance(items, dict):
        items = [items]
    return [
        {"name": i["name"], "type": i["type"], "size": i.get("size", 0), "path": i["path"]}
        for i in items
    ]


def get_file(token: str, repo: str, path: str, ref: str = "main") -> dict:
    """Get a file's content (decoded) and its SHA."""
    url = _repo_url(repo, f"contents/{path}")
    resp = httpx.get(url, headers=_headers(token), params={"ref": ref}, timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    content = ""
    if data.get("encoding") == "base64" and data.get("content"):
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return {"content": content, "sha": data["sha"], "path": data["path"], "size": data.get("size", 0)}


def search_code(token: str, repo: str, query: str) -> list[dict]:
    """Search for code in the repo using GitHub code search."""
    url = f"{_GITHUB_API}/search/code"
    params = {"q": f"{query} repo:{repo}", "per_page": 20}
    resp = httpx.get(url, headers=_headers(token), params=params, timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    return [
        {"path": item["path"], "name": item["name"]}
        for item in data.get("items", [])
    ]


def get_default_branch(token: str, repo: str) -> str:
    """Get the default branch name (main or master) for the repo."""
    url = _repo_url(repo)
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    return resp.json().get("default_branch", "main")


def get_branch_sha(token: str, repo: str, branch: str) -> str:
    """Get the HEAD SHA of a branch."""
    url = _repo_url(repo, f"git/ref/heads/{branch}")
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


def branch_exists(token: str, repo: str, branch_name: str) -> bool:
    """Check if a branch exists."""
    url = _repo_url(repo, f"git/ref/heads/{branch_name}")
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    return resp.status_code == 200


def create_branch(token: str, repo: str, branch_name: str, from_sha: str) -> bool:
    """Create a new branch from a given SHA. Returns False if branch already exists."""
    url = _repo_url(repo, "git/refs")
    resp = httpx.post(
        url,
        headers=_headers(token),
        json={"ref": f"refs/heads/{branch_name}", "sha": from_sha},
        timeout=_TIMEOUT,
    )
    _check_rate_limit(resp)
    if resp.status_code == 422:
        return False  # Already exists
    resp.raise_for_status()
    return True


def create_or_update_file(
    token: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str,
    sha: str | None = None,
) -> dict:
    """Create or update a file on a branch. Returns the new file SHA and commit SHA."""
    url = _repo_url(repo, f"contents/{path}")
    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    resp = httpx.put(url, headers=_headers(token), json=body, timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    return {"sha": data["content"]["sha"], "commit_sha": data["commit"]["sha"]}


def delete_file(
    token: str, repo: str, path: str, message: str, branch: str, sha: str,
) -> dict:
    """Delete a file on a branch."""
    url = _repo_url(repo, f"contents/{path}")
    body = {"message": message, "sha": sha, "branch": branch}
    resp = httpx.request("DELETE", url, headers=_headers(token), json=body, timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    return {"deleted": True, "commit_sha": resp.json()["commit"]["sha"]}


def create_pull_request(
    token: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> dict:
    """Create a pull request. Returns PR number, URL, title, and state."""
    url = _repo_url(repo, "pulls")
    resp = httpx.post(
        url,
        headers=_headers(token),
        json={"title": title, "body": body, "head": head, "base": base},
        timeout=_TIMEOUT,
    )
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    return {
        "number": data["number"],
        "url": data["html_url"],
        "title": data["title"],
        "state": data["state"],
    }


def get_pull_request(token: str, repo: str, number: int) -> dict:
    """Get PR details."""
    url = _repo_url(repo, f"pulls/{number}")
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    return {
        "number": data["number"],
        "url": data["html_url"],
        "title": data["title"],
        "state": data["state"],
        "merged": data.get("merged", False),
        "mergeable": data.get("mergeable"),
        "changed_files": data.get("changed_files", 0),
    }


def compare_branches(token: str, repo: str, base: str, head: str) -> list[dict]:
    """Compare two branches. Returns list of changed files."""
    url = _repo_url(repo, f"compare/{base}...{head}")
    resp = httpx.get(url, headers=_headers(token), timeout=_TIMEOUT)
    _check_rate_limit(resp)
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "filename": f["filename"],
            "status": f["status"],
            "additions": f["additions"],
            "deletions": f["deletions"],
        }
        for f in data.get("files", [])
    ]
