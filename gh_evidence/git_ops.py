"""Git operations: resolve repo, blame, expand commits."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class FileChange:
    """A file changed in a commit."""

    path: str
    status: str  # A, M, D, R, etc.


@dataclass
class CommitInfo:
    """Expanded commit metadata."""

    sha: str
    sha_full: str
    subject: str
    body: str
    author: str
    author_date: datetime
    committer: str
    committer_date: datetime
    files: list[FileChange]


def run_git(args: list[str], cwd: Path) -> str:
    """Run git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def run_git_allow_fail(args: list[str], cwd: Path) -> tuple[str, str, int]:
    """Run git, return (stdout, stderr, returncode)."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


def resolve_repo_and_file(
    file_path: str,
    cwd: Optional[Path] = None,
) -> tuple[Path, Path]:
    """
    Resolve repo root and normalized file path.
    Raises if not in a git worktree.
    """
    cwd = cwd or Path.cwd()
    cwd = cwd.resolve()

    root = run_git(["rev-parse", "--show-toplevel"], cwd).strip()
    repo_root = Path(root)

    # Normalize path: resolve relative to cwd, then make relative to repo
    resolved = (cwd / file_path).resolve()
    try:
        rel = resolved.relative_to(repo_root)
    except ValueError:
        raise SystemExit(f"File {file_path} is not under repo root {repo_root}")

    return repo_root, rel


def collect_blame_commits(
    repo_root: Path,
    file_path: Path,
    rev: str = "HEAD",
    since: Optional[str] = None,
    ignore_revs_file: Optional[Path] = None,
    max_commits: Optional[int] = None,
) -> list[str]:
    """
    Run git blame --line-porcelain, parse commit SHAs, dedupe.
    Optionally filter by commit date (--since) and limit count.
    """
    args = [
        "blame",
        "--line-porcelain",
        rev,
        "--",
        str(file_path),
    ]
    if ignore_revs_file and ignore_revs_file.exists():
        args.insert(2, f"--ignore-revs-file={ignore_revs_file}")

    out = run_git(args, repo_root)
    shas: set[str] = set()
    for line in out.splitlines():
        if line.startswith("author ") or line.startswith("committer "):
            continue
        if line.startswith("previous "):
            continue
        if line.startswith(" "):
            continue
        # Format: "sha line_no line_no count" or just "sha"
        parts = line.split()
        if parts and len(parts[0]) == 40 and parts[0].isalnum():
            shas.add(parts[0])

    sha_list = list(shas)

    if since or max_commits:
        # Expand all, order by date (newest first), then filter
        infos: list[tuple[str, CommitInfo]] = []
        for sha in sha_list:
            info = expand_commit(repo_root, sha)
            if since:
                try:
                    since_dt = datetime.strptime(since, "%Y-%m-%d")
                    if info.author_date.date() < since_dt.date():
                        continue
                except ValueError:
                    pass
            infos.append((sha, info))
        infos.sort(key=lambda x: x[1].author_date, reverse=True)
        sha_list = [s for s, _ in infos]
        if max_commits:
            sha_list = sha_list[:max_commits]

    elif max_commits:
        sha_list = sha_list[:max_commits]

    return sha_list


def expand_commit(repo_root: Path, sha: str) -> CommitInfo:
    """Get full commit metadata and files changed."""
    sha_full = run_git(["rev-parse", sha], repo_root).strip()

    meta_out = run_git(
        [
            "show",
            "--no-patch",
            "--format=%s%n%b%n%an%n%ai%n%cn%n%ci",
            sha,
        ],
        repo_root,
    )
    lines = [l.strip() for l in meta_out.strip().split("\n")]
    subject = lines[0] if lines else ""
    body = "\n".join(lines[1:-5]).strip() if len(lines) >= 6 else ""
    author = lines[-5] if len(lines) >= 6 else ""
    committer = lines[-3] if len(lines) >= 6 else ""
    author_date = datetime.now()
    committer_date = author_date
    if len(lines) >= 6:
        try:
            author_date = datetime.strptime(lines[-4][:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            pass
        try:
            committer_date = datetime.strptime(lines[-2][:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            committer_date = author_date

    # Files changed
    files_out = run_git(
        ["show", "--name-status", "--pretty=format:", sha],
        repo_root,
    )
    files: list[FileChange] = []
    for line in files_out.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        status = parts[0] if len(parts) > 0 else "M"
        path = parts[1] if len(parts) > 1 else ""
        if path:
            files.append(FileChange(path=path, status=status))

    return CommitInfo(
        sha=sha[:12],
        sha_full=sha_full,
        subject=subject,
        body=body,
        author=author,
        author_date=author_date,
        committer=committer,
        committer_date=committer_date,
        files=files,
    )
