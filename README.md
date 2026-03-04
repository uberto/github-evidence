# gh-evidence

Build **evidence packs** from git blame + GitHub PRs for any file. Deterministic up to the LLM summary step. Produces a single Markdown bundle you can feed to a remote LLM.

## Requirements

- **git** — repo must be a git worktree
- **gh** (GitHub CLI) — authenticated (`gh auth status`)
- **Python 3.10+**

## Install

```bash
pip install -e .
# or
pip install .
```

## Usage

```bash
gh-evidence path/to/file.py \
  --base origin/main \
  --since 2025-01-01 \
  --out evidence.md \
  --llm https://your-llm-endpoint/summarize
```

### Output

- **evidence.md** — raw, audit-friendly Markdown bundle
- **evidence.summary.json** — structured output from LLM (when `--llm` is used)
- **evidence.prompt.txt** — prompt sent to LLM (for traceability)

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base` | `origin/main` | Base branch for context |
| `--rev` | `HEAD` | Git revision to blame |
| `--since` | — | Filter commits by author date (`YYYY-MM-DD`) |
| `--max-commits` | — | Limit number of commits |
| `--ignore-revs-file` | — | Path to `.git-blame-ignore-revs` |
| `--out` | `evidence.md` | Output path for evidence pack |
| `--no-reviews` | — | Exclude PR reviews |
| `--no-comments` | — | Exclude PR comments |
| `--llm` | — | Remote LLM endpoint URL |
| `--llm-key` | — | Env var name for API key (e.g. `OPENAI_API_KEY`) |
| `--dry-run` | — | Generate MD only, skip LLM call |

## Pipeline (Stages)

1. **Resolve repo + file** — Ensure git worktree, normalize path
2. **Collect blame commits** — `git blame --line-porcelain`, parse SHAs, dedupe
3. **Expand commit metadata** — `git show` for author, date, message, files changed
4. **Map commits → PRs** — `gh pr list --search` + `gh api .../commits/.../pulls`
5. **Fetch PR discussion** — Comments + reviews via `gh pr view`
6. **Write evidence pack** — Structured Markdown
7. **LLM summary** (optional) — POST to remote endpoint, write JSON

## LLM Endpoint

The `--llm` URL should accept a POST with JSON body:

```json
{
  "prompt": "...",
  "evidence": "..."
}
```

And return JSON with a text field in one of these shapes:

- `{"choices": [{"message": {"content": "..."}}]}`
- `{"content": [{"text": "..."}]}`
- `{"output": "..."}`

The response should be valid JSON matching the schema:

```json
{
  "file": "...",
  "key_changes": [{"when": "", "what": "", "commit": "", "pr": ""}],
  "recurring_themes": [],
  "risky_areas": [],
  "open_questions": [],
  "glossary": [{"term": "", "meaning": ""}],
  "people_involved": [{"who": "", "context": ""}],
  "next_steps": []
}
```

## Edge Cases

- **Huge files** — Use `--max-commits` or `--since` to limit
- **Generated / vendored code** — Use `--ignore-revs-file` or path exclude
- **Squash merges** — Commits may map poorly to PRs; fallback to API
- **Monorepos** — Use `--no-reviews` / `--no-comments` to reduce noise
