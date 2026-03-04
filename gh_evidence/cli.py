"""CLI entry point for gh-evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .gh_ops import commits_to_prs, fetch_pr_discussion
from .git_ops import collect_blame_commits, expand_commit, resolve_repo_and_file
from .llm_summary import PROMPT_TEMPLATE, SUMMARY_SCHEMA, get_llm_summary, write_summary_and_prompt
from .writer import write_evidence_pack


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gh-evidence",
        description="Build evidence packs from git blame + GitHub PRs for any file",
    )
    parser.add_argument(
        "file",
        help="Path to the target file (relative to cwd or repo root)",
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base branch for context (default: origin/main)",
    )
    parser.add_argument(
        "--rev",
        default="HEAD",
        help="Git revision to blame (default: HEAD)",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Filter commits by author date (>= since)",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        metavar="N",
        help="Limit number of commits to include",
    )
    parser.add_argument(
        "--ignore-revs-file",
        type=Path,
        metavar="PATH",
        help="Path to .git-blame-ignore-revs file",
    )
    parser.add_argument(
        "--out",
        default="evidence.md",
        metavar="PATH",
        help="Output path for evidence pack (default: evidence.md)",
    )
    parser.add_argument(
        "--no-reviews",
        action="store_true",
        help="Exclude PR reviews from evidence pack",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Exclude PR comments from evidence pack",
    )
    parser.add_argument(
        "--llm",
        metavar="URL",
        help="Remote LLM endpoint URL for structured summary",
    )
    parser.add_argument(
        "--llm-key",
        metavar="ENVVAR",
        help="Environment variable name for API key (e.g. OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate Markdown only, do not call LLM",
    )

    args = parser.parse_args()

    cwd = Path.cwd()

    # 1) Resolve repo + target file
    try:
        repo_root, file_path = resolve_repo_and_file(args.file, cwd)
    except SystemExit as e:
        sys.exit(e.code if isinstance(e.code, int) else 1)

    out_path = (cwd / args.out).resolve()
    out_stem = out_path.stem
    out_dir = out_path.parent
    summary_path = out_dir / f"{out_stem}.summary.json"
    prompt_path = out_dir / f"{out_stem}.prompt.txt"

    # 2) Collect blame commits
    ignore_revs = args.ignore_revs_file
    if ignore_revs and not ignore_revs.is_absolute():
        ignore_revs = cwd / ignore_revs

    shas = collect_blame_commits(
        repo_root,
        file_path,
        rev=args.rev,
        since=args.since,
        ignore_revs_file=ignore_revs,
        max_commits=args.max_commits,
    )

    if not shas:
        print("No commits found from blame.", file=sys.stderr)
        sys.exit(0)

    # 3) Expand commit metadata
    commits: list[tuple[str, CommitInfo]] = []
    for sha in shas:
        info = expand_commit(repo_root, sha)
        commits.append((sha, info))

    # 4) Map commits → PRs
    sha_to_prs = commits_to_prs(repo_root, shas)

    # 5) Fetch PR discussion
    pr_details: dict[int, PRInfo] = {}
    seen_prs: set[int] = set()
    for prs in sha_to_prs.values():
        for pr in prs:
            if pr.number not in seen_prs:
                seen_prs.add(pr.number)
                full_pr = fetch_pr_discussion(
                    repo_root,
                    pr.number,
                    include_comments=not args.no_comments,
                    include_reviews=not args.no_reviews,
                )
                pr_details[pr.number] = full_pr

    # Merge basic PR info into pr_details for PRs that had no discussion fetch
    for prs in sha_to_prs.values():
        for pr in prs:
            if pr.number not in pr_details:
                pr_details[pr.number] = pr

    # 6) Write evidence pack
    write_evidence_pack(
        out_path,
        repo_root,
        file_path,
        args.rev,
        commits,
        sha_to_prs,
        pr_details,
        include_raw=True,
    )
    print(f"Wrote {out_path}")

    # 7) LLM summary (optional)
    if args.llm and not args.dry_run:
        try:
            summary = get_llm_summary(
                out_path,
                args.llm,
                api_key_envvar=args.llm_key,
            )
            schema_str = json.dumps(SUMMARY_SCHEMA, indent=2)
            prompt = PROMPT_TEMPLATE.format(
                schema=schema_str,
                evidence=out_path.read_text(encoding="utf-8"),
            )
            write_summary_and_prompt(summary, summary_path, prompt_path, prompt)
            print(f"Wrote {summary_path}")
        except Exception as e:
            print(f"LLM summary failed: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.dry_run:
        print("Dry run: skipped LLM call.")


if __name__ == "__main__":
    main()
