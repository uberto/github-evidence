"""Evidence pack Markdown writer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .gh_ops import PRInfo
from .git_ops import CommitInfo, FileChange


def write_evidence_pack(
    out_path: Path,
    repo_root: Path,
    file_path: Path,
    base_rev: str,
    commits: list[tuple[str, CommitInfo]],
    sha_to_prs: dict[str, list[PRInfo]],
    pr_details: dict[int, PRInfo],
    include_raw: bool = True,
) -> None:
    """
    Write the evidence pack Markdown file.
    Structure: header, summary, Section A (blame commits), Section B (PR details), appendix.
    """
    lines: list[str] = []
    generated = datetime.now().isoformat()

    # Header
    lines.append(f"# Evidence Pack: `{file_path}`")
    lines.append("")
    lines.append(f"- **Repository:** `{repo_root}`")
    lines.append(f"- **File:** `{file_path}`")
    lines.append(f"- **Base revision:** `{base_rev}`")
    lines.append(f"- **Generated:** {generated}")
    lines.append("")

    # Summary counts
    unique_prs = set()
    for prs in sha_to_prs.values():
        for pr in prs:
            unique_prs.add(pr.number)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Unique commits (blame):** {len(commits)}")
    lines.append(f"- **Unique PRs:** {len(unique_prs)}")
    lines.append("")

    # Section A: Blame commits (ordered by recency)
    lines.append("---")
    lines.append("## A. Blame Commits")
    lines.append("")
    for sha, info in commits:
        lines.append(f"### `{info.sha}` — {info.subject}")
        lines.append("")
        lines.append(f"- **Date:** {info.author_date.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"- **Author:** {info.author}")
        if info.body:
            lines.append("")
            lines.append("**Message body:**")
            lines.append("")
            lines.append("```")
            lines.append(info.body)
            lines.append("```")
            lines.append("")
        lines.append("**Files touched:**")
        for fc in info.files:
            lines.append(f"- `{fc.status}` {fc.path}")
        lines.append("")
        prs = sha_to_prs.get(sha, [])
        if prs:
            lines.append("**Linked PR(s):**")
            for pr in prs:
                lines.append(f"- [#{pr.number}]({pr.url}) {pr.title}")
            lines.append("")
        lines.append("---")
        lines.append("")

    # Section B: PR details
    lines.append("## B. PR Details")
    lines.append("")
    for pr_num in sorted(unique_prs):
        pr = pr_details.get(pr_num)
        if not pr:
            continue
        lines.append(f"### PR #{pr.number}: {pr.title}")
        lines.append("")
        lines.append(f"- **URL:** {pr.url}")
        lines.append(f"- **State:** {pr.state}")
        lines.append(f"- **Author:** {pr.author}")
        lines.append(f"- **Created:** {pr.created_at}")
        if pr.merged_at:
            lines.append(f"- **Merged:** {pr.merged_at}")
        lines.append("")
        if pr.body:
            lines.append("**Description:**")
            lines.append("")
            lines.append(pr.body)
            lines.append("")
        if pr.comments:
            lines.append("**Comments:**")
            lines.append("")
            for c in pr.comments:
                author = c.get("author", "")
                body = c.get("body", "")
                created = c.get("createdAt", "")
                lines.append(f"- *{author}* ({created}):")
                lines.append("")
                lines.append(f"  {_indent_block(body)}")
                lines.append("")
        if pr.reviews:
            lines.append("**Reviews:**")
            lines.append("")
            for r in pr.reviews:
                author = r.get("author", "")
                state = r.get("state", "")
                body = r.get("body", "")
                created = r.get("createdAt", "")
                lines.append(f"- *{author}* — `{state}` ({created})")
                if body:
                    lines.append("")
                    lines.append(f"  {_indent_block(body)}")
                lines.append("")
        lines.append("---")
        lines.append("")

    # Appendix: raw outputs (optional)
    if include_raw:
        lines.append("<details>")
        lines.append("<summary>Appendix: Raw command outputs</summary>")
        lines.append("")
        lines.append("```")
        lines.append(f"# git blame --line-porcelain {base_rev} -- {file_path}")
        lines.append("# (output omitted for brevity)")
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _indent_block(text: str, indent: str = "  ") -> str:
    """Indent a multi-line block."""
    return "\n".join(indent + line for line in (text or "").split("\n"))
