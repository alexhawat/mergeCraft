name: mergeCraft

on:
  # Auto-review on PR open / ready / new commits. mergeCraft reads the native
  # GITHUB_EVENT_PATH, so no ~mergecraft JSON payload is needed — just a prompt.
  pull_request:
    types: [opened, ready_for_review, synchronize]
  # On-demand runs without a comment trigger. To drive mergeCraft interactively,
  # use `workflow_dispatch` (below) or trigger a `pull_request` push — comment
  # triggers are intentionally omitted because any commenter can otherwise steer
  # the agent (issue #72 / D5). See README for the authorization model.
  workflow_dispatch:
    inputs:
      prompt:
        description: Prompt for the agent
        required: true
        type: string

permissions:
  contents: write
  pull-requests: write
  issues: write
  checks: write
  actions: read
  id-token: write

jobs:
  mergecraft:
    if: >
      github.event_name == 'pull_request' ||
      github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Optional: mint a short-lived installation token for elevated API access
      # - name: Get installation token
      #   id: token
      #   uses: ./get-installation-token
      #   env:
      #     GITHUB_APP_ID: ${{ secrets.MERGECRAFT_APP_ID }}
      #     GITHUB_APP_PRIVATE_KEY: ${{ secrets.MERGECRAFT_APP_PRIVATE_KEY }}

      - name: Run mergeCraft
        uses: __ACTION_REPO__@__ACTION_PIN__
        with:
          prompt: >
            ${{ github.event_name == 'pull_request'
                && 'Review this pull request.'
                || github.event.inputs.prompt }}
          # #37 / W4 — a single ``uses:`` step walks the configured chain.
          # The ``model:`` input is the chain head; configure the tail via
          # ``models:`` in `.mergecraft/config.yaml`. Uncredentialed entries
          # are skipped with a warning; retryable failures advance. Set
          # ``model_pin: enabled`` ONLY if you want to suppress fallbacks.
          model: anthropic/claude-sonnet
          # model_pin: enabled   # uncomment to suppress fallbacks (legacy semantics)
          # Post mergecraft / mergecraft-approval commit-status checks (gate on approval).
          status_checks: enabled
          # token: ${{ steps.token.outputs.token }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          # CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
          # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}           # + model: nous/deepseek/deepseek-v4-flash
          # TOKENHUB_API_KEY: ${{ secrets.TOKENHUB_API_KEY }}   # + model: tokenhub/hy3
          # GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}       # + model: google/gemini-*
