# End-to-end testing — remaining steps

This document tracks what is left to run the Mistral issue-to-PR workflow
end-to-end. The repository under test is `Nicodl05/ai-agent-workflows` itself
(it both hosts the reusable workflow and calls it).

## Already done

- [x] Reusable workflow `.github/workflows/mistral-issue.yml` pushed to `main`.
- [x] Caller workflow `.github/workflows/mistral-caller.yml` pushed to `main`.
- [x] Label `mistral` created (triggers the agent).
- [x] Label `awaiting-review` created (applied to the generated PR).

## TODO — set the two secrets

Neither secret is set yet. `ANTHROPIC_API_KEY` exists on the repo but is a
leftover from the Claude setup and is not used here.

### 1. Mistral API key

Get a key from https://console.mistral.ai (API Keys), then run:

```bash
gh secret set AI_API_KEY --repo Nicodl05/ai-agent-workflows
```

Paste the value when prompted (it is not echoed).

### 2. GitHub PAT

Create a fine-grained token at
github.com > Settings > Developer settings > Personal access tokens > Fine-grained,
scoped to the `ai-agent-workflows` repository with these permissions:

| Permission | Access |
|---|---|
| Contents | Read and write |
| Workflows | Read and write |
| Issues | Read and write |
| Pull requests | Read and write |

Then run:

```bash
gh secret set GH_PAT --repo Nicodl05/ai-agent-workflows
```

Verify both are present:

```bash
gh secret list --repo Nicodl05/ai-agent-workflows
# expected: AI_API_KEY and GH_PAT
```

## TODO — trigger the test

Once both secrets are set, create a simple issue and label it `mistral`:

```bash
gh issue create \
  --repo Nicodl05/ai-agent-workflows \
  --title "Add a CONTRIBUTING.md" \
  --body "Create a CONTRIBUTING.md at the repo root with a short contribution guide." \
  --label mistral
```

(Adding the `mistral` label to any existing open issue works too.)

## TODO — observe the result

In the Actions tab (or via CLI), check that the run:

1. Creates a branch `feature/issue-{N}-add-a-contributing-md`.
2. Commits with `feat: implement issue #{N} via Mistral`.
3. Opens a PR labelled `awaiting-review` that closes the issue.
4. Comments on the issue with the PR URL.
5. Did NOT modify anything under `.github/workflows/`.

```bash
gh run list --repo Nicodl05/ai-agent-workflows --limit 5
gh run watch --repo Nicodl05/ai-agent-workflows
```

## Optional — local-only test (no GitHub run)

Faster smoke test of the agent script alone:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AI_PROVIDER=mistral
export AI_API_KEY="your_mistral_key"
export ISSUE_NUMBER=1
export ISSUE_TITLE="Add a hello world script"
export ISSUE_BODY="Create scripts/hello.py that prints Hello World."
export REPO="Nicodl05/ai-agent-workflows"
python scripts/ai_agent.py
git status          # check generated files, nothing under .github/workflows/
git checkout .      # discard test output
```
