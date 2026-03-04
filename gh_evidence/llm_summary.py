"""Remote LLM summary: send evidence pack, get structured JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

SUMMARY_SCHEMA = {
    "file": "string",
    "key_changes": [{"when": "", "what": "", "commit": "", "pr": ""}],
    "recurring_themes": [],
    "risky_areas": [],
    "open_questions": [],
    "glossary": [{"term": "", "meaning": ""}],
    "people_involved": [{"who": "", "context": ""}],
    "next_steps": [],
}

PROMPT_TEMPLATE = """You are analyzing an evidence pack for a source file. The pack contains git blame data (commits that last touched each line), PR metadata, and discussion comments.

Extract and summarize the key information into the following JSON structure. Be concise and factual.

Return ONLY valid JSON, no markdown or other text.

Schema:
{schema}

Evidence pack content:
---
{evidence}
---
"""


def get_llm_summary(
    evidence_path: Path,
    llm_url: str,
    api_key_envvar: Optional[str] = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """
    POST evidence.md to LLM endpoint, parse JSON response.
    API key from env var if api_key_envvar is set.
    """
    evidence = evidence_path.read_text(encoding="utf-8")
    schema_str = json.dumps(SUMMARY_SCHEMA, indent=2)
    prompt = PROMPT_TEMPLATE.format(schema=schema_str, evidence=evidence)

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key_envvar:
        key = os.environ.get(api_key_envvar)
        if key:
            headers["Authorization"] = f"Bearer {key}"

    try:
        import httpx
    except ImportError:
        raise ImportError("httpx is required for --llm. Install with: pip install httpx") from None

    # Generic: send prompt + evidence. Custom endpoints can expect different shapes.
    body: dict[str, Any] = {"prompt": prompt, "evidence": evidence}

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(llm_url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # Extract content from common response shapes
    content = ""
    if isinstance(data, dict):
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
            or data.get("content", [{}])[0].get("text", "")
            if isinstance(data.get("content"), list)
            else data.get("content", "")
            or data.get("output", "")
            or str(data)
        )
    else:
        content = str(data)

    # Strip markdown code blocks if present
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    return json.loads(content)


def write_summary_and_prompt(
    summary: dict[str, Any],
    out_path: Path,
    prompt_path: Optional[Path] = None,
    prompt: Optional[str] = None,
) -> None:
    """Write evidence.summary.json and optionally the prompt for traceability."""
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if prompt_path and prompt:
        prompt_path.write_text(prompt, encoding="utf-8")
