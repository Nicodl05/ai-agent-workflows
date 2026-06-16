"""Provider-agnostic AI agent that implements a GitHub issue.

The script reads issue context from environment variables, calls an
OpenAI-compatible chat completions endpoint (Mistral by default), and applies
the returned file changes to the working tree.

The model is asked to return a strict JSON array of file operations:

    [{"path": "...", "action": "create|update|delete", "content": "..."}]

Any path under ``.github/workflows/`` is ignored as a safety measure so the
agent can never tamper with CI workflow definitions in the target repository.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from openai import OpenAI, OpenAIError

# Exit codes used to signal distinct failure classes to the workflow.
EXIT_OK: Final = 0
EXIT_MISSING_KEY: Final = 1
EXIT_INVALID_JSON: Final = 2
EXIT_API_ERROR: Final = 3
EXIT_CONFIG_ERROR: Final = 4

# Paths matching this prefix are never written or deleted by the agent.
PROTECTED_PREFIX: Final = ".github/workflows/"

# Default provider when AI_PROVIDER is unset.
DEFAULT_PROVIDER: Final = "mistral"

# Static provider mapping: provider -> (base_url, default_model).
# A value of None means the corresponding env var must supply it.
PROVIDER_DEFAULTS: Final[dict[str, tuple[str | None, str | None]]] = {
    "mistral": ("https://api.mistral.ai/v1", "mistral-medium-latest"),
    "openrouter": ("https://openrouter.ai/api/v1", None),
    "custom": (None, None),
}

Action = Literal["create", "update", "delete"]


@dataclass(frozen=True)
class IssueContext:
    """Issue metadata used to build the user prompt."""

    number: str
    title: str
    body: str
    repo: str


@dataclass(frozen=True)
class FileChange:
    """A single file operation requested by the model."""

    path: str
    action: Action
    content: str


def log(message: str) -> None:
    """Write a timestamped-free log line to stderr for workflow output."""
    print(f"[ai_agent] {message}", file=sys.stderr, flush=True)


def fail(code: int, message: str) -> "NoReturn":  # type: ignore[name-defined]
    """Log an error and terminate with the given exit code."""
    log(f"ERROR: {message}")
    sys.exit(code)


def resolve_provider() -> tuple[str, str, str]:
    """Resolve the (provider, base_url, model) triple from the environment.

    Raises a clean exit on configuration errors (e.g. a custom provider
    without a base URL or model).
    """
    provider = (os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    if provider not in PROVIDER_DEFAULTS:
        fail(
            EXIT_CONFIG_ERROR,
            f"unknown provider '{provider}'. "
            f"Supported: {', '.join(PROVIDER_DEFAULTS)}",
        )

    default_base_url, default_model = PROVIDER_DEFAULTS[provider]
    base_url = (os.environ.get("AI_BASE_URL") or default_base_url or "").strip()
    model = (os.environ.get("AI_MODEL") or default_model or "").strip()

    if not base_url:
        fail(
            EXIT_CONFIG_ERROR,
            f"provider '{provider}' requires AI_BASE_URL to be set",
        )
    if not model:
        fail(
            EXIT_CONFIG_ERROR,
            f"provider '{provider}' requires AI_MODEL to be set",
        )

    return provider, base_url, model


def read_issue_context() -> IssueContext:
    """Build the issue context from environment variables."""
    return IssueContext(
        number=(os.environ.get("ISSUE_NUMBER") or "").strip(),
        title=(os.environ.get("ISSUE_TITLE") or "").strip(),
        body=os.environ.get("ISSUE_BODY") or "",
        repo=(os.environ.get("REPO") or "").strip(),
    )


def load_system_prompt() -> str:
    """Load CLAUDE.md from the current repo as a system prompt if present."""
    claude_md = Path("CLAUDE.md")
    base_instructions = (
        "You are an autonomous software engineer implementing a GitHub issue. "
        "Apply clean code, strict typing where supported, and write tests when "
        "relevant. Use English for all code, comments, and identifiers. "
        "Never modify files under .github/workflows/."
    )
    if claude_md.is_file():
        repo_instructions = claude_md.read_text(encoding="utf-8")
        log("Loaded CLAUDE.md as additional system context.")
        return f"{base_instructions}\n\nRepository conventions:\n{repo_instructions}"
    log("No CLAUDE.md found; using base system prompt only.")
    return base_instructions


def build_user_prompt(issue: IssueContext) -> str:
    """Build the user prompt instructing the model to return JSON changes."""
    return (
        f"Repository: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n\n"
        f"Issue description:\n{issue.body}\n\n"
        "Implement the changes required to resolve this issue.\n\n"
        "Respond with ONLY a JSON array, no prose, no markdown fences. "
        "Each element must be an object with exactly these keys:\n"
        '  "path": repository-relative file path (string)\n'
        '  "action": one of "create", "update", or "delete"\n'
        '  "content": full file content for create/update, '
        'empty string for delete\n\n'
        "Do not include any path under .github/workflows/. "
        "Return an empty array if no change is needed."
    )


def strip_code_fences(raw: str) -> str:
    """Remove surrounding markdown code fences from the model output."""
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence (``` or ```json) and a trailing fence if present.
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_changes(raw: str) -> list[FileChange]:
    """Parse and validate the model output into a list of file changes."""
    cleaned = strip_code_fences(raw)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        fail(EXIT_INVALID_JSON, f"model did not return valid JSON: {exc}")

    if not isinstance(payload, list):
        fail(EXIT_INVALID_JSON, "expected a JSON array of file changes")

    changes: list[FileChange] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            fail(EXIT_INVALID_JSON, f"item {index} is not an object")
        path = item.get("path")
        action = item.get("action")
        content = item.get("content", "")
        if not isinstance(path, str) or not path.strip():
            fail(EXIT_INVALID_JSON, f"item {index} has an invalid 'path'")
        if action not in ("create", "update", "delete"):
            fail(EXIT_INVALID_JSON, f"item {index} has an invalid 'action'")
        if not isinstance(content, str):
            fail(EXIT_INVALID_JSON, f"item {index} has a non-string 'content'")
        changes.append(FileChange(path=path.strip(), action=action, content=content))
    return changes


def is_protected(path: str) -> bool:
    """Return True if a path must never be touched by the agent."""
    normalized = path
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.startswith(PROTECTED_PREFIX)


def apply_changes(changes: list[FileChange]) -> None:
    """Apply file changes to the working tree, skipping protected paths."""
    if not changes:
        log("Model returned no changes to apply.")
        return

    for change in changes:
        if is_protected(change.path):
            log(f"SKIP protected path: {change.path}")
            continue

        target = Path(change.path)
        if change.action == "delete":
            if target.is_file():
                target.unlink()
                log(f"DELETE {change.path}")
            else:
                log(f"DELETE skipped, file not found: {change.path}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(change.content, encoding="utf-8")
        log(f"{change.action.upper()} {change.path}")


def call_model(
    api_key: str, base_url: str, model: str, system_prompt: str, user_prompt: str
) -> str:
    """Call the chat completions endpoint and return the raw message content."""
    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
    except OpenAIError as exc:
        fail(EXIT_API_ERROR, f"API call failed: {exc}")

    content = response.choices[0].message.content
    if not content:
        fail(EXIT_API_ERROR, "API returned an empty response")
    return content


def main() -> int:
    """Entry point: resolve config, call the model, apply changes."""
    api_key = (os.environ.get("AI_API_KEY") or "").strip()
    if not api_key:
        fail(EXIT_MISSING_KEY, "AI_API_KEY is not set")

    provider, base_url, model = resolve_provider()
    issue = read_issue_context()
    if not issue.number:
        fail(EXIT_CONFIG_ERROR, "ISSUE_NUMBER is not set")

    log(f"Provider: {provider} | Base URL: {base_url} | Model: {model}")
    log(f"Implementing issue #{issue.number}: {issue.title}")

    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(issue)

    raw = call_model(api_key, base_url, model, system_prompt, user_prompt)
    changes = parse_changes(raw)
    apply_changes(changes)

    log(f"Done. Applied {len(changes)} change(s) (protected paths excluded).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
