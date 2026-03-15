"""GitHub operations via gh CLI: map commits to PRs, fetch discussion."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class PRInfo:
    """PR metadata from GitHub."""

    number: int
    title: str
    url: str
    state: str
    body: str
    author: str
    created_at: str
    merged_at: Optional[str]
    labels: list[str] = field(default_factory=list)
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    comments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)


def run_gh(args: list[str], cwd: Path) -> tuple[str, str, int]:
    """Run gh command, return (stdout, stderr, returncode)."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "gh CLI not found. Install from https://cli.github.com/", 127


def get_repo_owner_name(repo_root: Path) -> Optional[tuple[str, str]]:
    """Get owner/repo from git remote. Returns (owner, repo) or None."""
    out, _, code = run_gh(["repo", "view", "--json", "owner,name"], repo_root)
    if code != 0:
        return None
    try:
        data = json.loads(out)
        return data.get("owner", {}).get("login"), data.get("name")
    except (json.JSONDecodeError, TypeError):
        return None


def commits_to_prs(
    repo_root: Path,
    shas: list[str],
) -> dict[str, list[PRInfo]]:
    """
    Map each commit SHA to zero or more PRs.
    Uses gh pr list --search and gh api .../commits/.../pulls as fallback.
    """
    sha_to_prs: dict[str, list[PRInfo]] = {sha: [] for sha in shas}
    seen_pr_numbers: set[int] = set()
    pr_cache: dict[int, PRInfo] = {}

    for sha in shas:
        # Strategy 1: gh pr list --search "sha"
        out, _, code = run_gh(
            ["pr", "list", "--search", sha, "--json", "number,title,url,state,body,author,createdAt,mergedAt,baseRefName,headRefName"],
            repo_root,
        )
        if code == 0 and out.strip():
            try:
                prs = json.loads(out)
                for p in prs:
                    num = p.get("number")
                    if num and num not in seen_pr_numbers:
                        seen_pr_numbers.add(num)
                        pr_info = _parse_pr(p)
                        pr_cache[num] = pr_info
                        sha_to_prs[sha].append(pr_info)
            except json.JSONDecodeError:
                pass

        # Strategy 2: if no PR found, try commits/.../pulls API
        if not sha_to_prs[sha]:
            owner, repo = get_repo_owner_name(repo_root) or (None, None)
            if owner and repo:
                out, _, code = run_gh(
                    [
                        "api",
                        "-H", "Accept: application/vnd.github+json",
                        "-H", "X-GitHub-Api-Version: 2022-11-28",
                        f"repos/{owner}/{repo}/commits/{sha}/pulls",
                    ],
                    repo_root,
                )
                if code == 0 and out.strip() and out.strip() != "[]":
                    try:
                        prs = json.loads(out)
                        for p in prs:
                            num = p.get("number")
                            if num and num not in seen_pr_numbers:
                                seen_pr_numbers.add(num)
                                pr_info = _parse_pr_api(p)
                                pr_cache[num] = pr_info
                                sha_to_prs[sha].append(pr_info)
                    except json.JSONDecodeError:
                        pass

    return sha_to_prs


def _parse_pr(p: dict) -> PRInfo:
    author = ""
    if isinstance(p.get("author"), dict):
        author = p["author"].get("login", "")
    elif isinstance(p.get("author"), str):
        author = p["author"]
    return PRInfo(
        number=p.get("number", 0),
        title=p.get("title", ""),
        url=p.get("url", ""),
        state=p.get("state", "OPEN"),
        body=p.get("body") or "",
        author=author,
        created_at=p.get("createdAt", ""),
        merged_at=p.get("mergedAt"),
        base_ref=p.get("baseRefName"),
        head_ref=p.get("headRefName"),
    )


def _parse_pr_api(p: dict) -> PRInfo:
    author = ""
    if isinstance(p.get("user"), dict):
        author = p["user"].get("login", "")
    return PRInfo(
        number=p.get("number", 0),
        title=p.get("title", ""),
        url=p.get("html_url", p.get("url", "")),
        state="MERGED" if p.get("merged_at") else ("CLOSED" if p.get("closed_at") else "OPEN"),
        body=p.get("body") or "",
        author=author,
        created_at=p.get("created_at", ""),
        merged_at=p.get("merged_at"),
        base_ref=p.get("base", {}).get("ref") if isinstance(p.get("base"), dict) else None,
        head_ref=p.get("head", {}).get("ref") if isinstance(p.get("head"), dict) else None,
    )


def fetch_pr_discussion(
    repo_root: Path,
    pr_number: int,
    include_comments: bool = True,
    include_reviews: bool = True,
) -> PRInfo:
    """
    Fetch PR body, comments, and reviews.
    Merges into existing PRInfo if provided.
    """
    json_fields = ["body", "title", "url", "author", "createdAt", "state", "mergedAt"]
    if include_comments:
        json_fields.append("comments")
    if include_reviews:
        json_fields.append("reviews")

    out, _, code = run_gh(
        ["pr", "view", str(pr_number), "--json", ",".join(json_fields)],
        repo_root,
    )
    if code != 0:
        return PRInfo(number=pr_number, title="", url="", state="", body="", author="", created_at="", merged_at=None)

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return PRInfo(number=pr_number, title="", url="", state="", body="", author="", created_at="", merged_at=None)

    author = ""
    if isinstance(data.get("author"), dict):
        author = data["author"].get("login", "")

    comments: list[dict[str, Any]] = []
    for c in data.get("comments") or []:
        comments.append({
            "author": c.get("author", {}).get("login", "") if isinstance(c.get("author"), dict) else "",
            "body": c.get("body", ""),
            "createdAt": c.get("createdAt", ""),
        })

    reviews: list[dict[str, Any]] = []
    for r in data.get("reviews") or []:
        reviews.append({
            "author": r.get("author", {}).get("login", "") if isinstance(r.get("author"), dict) else "",
            "state": r.get("state", ""),
            "body": r.get("body", ""),
            "createdAt": r.get("createdAt", ""),
        })

    return PRInfo(
        number=pr_number,
        title=data.get("title", ""),
        url=data.get("url", ""),
        state=data.get("state", "OPEN"),
        body=data.get("body") or "",
        author=author,
        created_at=data.get("createdAt", ""),
        merged_at=data.get("mergedAt"),
        comments=comments,
        reviews=reviews,
    )
