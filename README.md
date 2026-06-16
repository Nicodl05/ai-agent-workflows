# ai-agent-workflows

Reusable GitHub Actions workflow that automatically implements a labelled issue
in the cloud using the Mistral API (or any OpenAI-compatible provider) and opens
a pull request.

When an issue is labelled `mistral`, a hosted GitHub runner:

1. Creates a branch `feature/issue-{number}-{slug}` from `main`.
2. Runs `scripts/ai_agent.py`, which sends the issue to the Mistral chat
   completions endpoint and applies the returned file changes.
3. Resets `.github/workflows/` so CI definitions in the target repo are never
   modified.
4. Commits with a conventional message and pushes the branch.
5. Opens a pull request that closes the issue, tagged `awaiting-review`.
6. Comments on the issue with the pull request URL.

Everything runs on a GitHub-hosted runner. No self-hosted infrastructure is
required.

## Note on the Claude case

This repository covers **only** the Mistral cloud provider. The Claude case is
handled **separately and locally** via the `/fetch-issues` slash command in
Claude Code. Do not look for or add a Claude workflow here.

## How to add the workflow to a project

### 1. Copy the caller workflow

Copy [`docs/mistral-caller.yml`](docs/mistral-caller.yml) into the target
project at `.github/workflows/mistral-issue.yml`:

```yaml
name: Mistral Issue Handler

on:
  issues:
    types: [labeled]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  mistral:
    if: github.event.label.name == 'mistral'
    uses: Nicodl05/ai-agent-workflows/.github/workflows/mistral-issue.yml@main
    with:
      issue_number: ${{ github.event.issue.number }}
      issue_title: ${{ github.event.issue.title }}
      issue_body: ${{ github.event.issue.body || '' }}
    secrets:
      AI_API_KEY: ${{ secrets.AI_API_KEY }}
      GH_PAT: ${{ secrets.GH_PAT }}
```

### 2. Configure repository variables (optional)

The provider defaults to Mistral. Override it through **Settings > Secrets and
variables > Actions > Variables**:

| Variable | Default | When to set |
|---|---|---|
| `AI_PROVIDER` | `mistral` | `openrouter` or `custom` to switch provider |
| `AI_MODEL` | provider default | Required for `openrouter` and `custom` |
| `AI_BASE_URL` | provider default | Required for `custom` |

With the default `mistral` provider the model is `mistral-medium-latest` and no
variable is needed.

### 3. Add repository secrets

In **Settings > Secrets and variables > Actions > Secrets**:

| Secret | Value |
|---|---|
| `AI_API_KEY` | API key for the chosen provider |
| `GH_PAT` | GitHub Personal Access Token (see scopes below) |

The PAT is required because the default `GITHUB_TOKEN` cannot trigger downstream
workflows or push protected paths. Create a fine-grained token at
**github.com > Settings > Developer settings > Personal access tokens** with
these repository permissions:

| Permission | Access |
|---|---|
| Contents | Read and write |
| Workflows | Read and write |
| Issues | Read and write |
| Pull requests | Read and write |

### 4. Create the `mistral` label

In the target repository, go to **Issues > Labels** and create a label named
exactly `mistral`. Adding it to any open issue triggers the workflow.

## Supported providers

| Provider | `AI_PROVIDER` | Base URL | Default model | Free tier |
|---|---|---|---|---|
| Mistral | `mistral` | `https://api.mistral.ai/v1` | `mistral-medium-latest` | Free experimentation tier with rate limits on `la Plateforme` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | set via `AI_MODEL` | Several `:free` models available at no cost |
| Custom | `custom` | set via `AI_BASE_URL` | set via `AI_MODEL` | Depends on the upstream OpenAI-compatible endpoint |

## Repository layout

```
ai-agent-workflows/
├── .github/workflows/
│   └── mistral-issue.yml      # reusable workflow (workflow_call)
├── scripts/
│   └── ai_agent.py            # provider-agnostic implementation agent
├── docs/
│   └── mistral-caller.yml     # caller workflow to copy into each project
├── requirements.txt
└── README.md
```
