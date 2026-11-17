# Optional consumer workflow. Copy to .github/workflows/mergecraft-discuss.yml.
# Pin a deployed Action commit whose metadata and runtime image support Discuss.
name: mergeCraft Discuss

on:
  pull_request_review_comment:
    types: [created]

# The GitHub App token below supplies the only repository write permission.
permissions: {}

concurrency:
  group: mergecraft-discuss-${{ github.event.comment.id }}
  cancel-in-progress: false

jobs:
  discuss:
    if: >-
      github.event.pull_request.head.repo.full_name == github.repository &&
      github.event.comment.in_reply_to_id &&
      github.event.sender.type == 'User' &&
      contains(github.event.comment.body, '@mergecraft') &&
      contains(fromJSON('["OWNER","MEMBER","COLLABORATOR"]'), github.event.comment.author_association)
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - name: Mint the reviewer App token
        id: reviewer
        uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510 # v3.3.0
        with:
          app-id: ${{ secrets.MERGECRAFT_APP_ID }}
          private-key: ${{ secrets.MERGECRAFT_APP_PRIVATE_KEY }}
          permission-pull-requests: write
      - name: Answer the inline thread
        uses: __ACTION_REPO__@REPLACE_WITH_DISCUSS_CAPABLE_SHA
        with:
          discuss: enabled
          model: opencode-go/deepseek-v4.1-flash
          token: ${{ steps.reviewer.outputs.token }}
        env:
          MERGECRAFT_REVIEWER_BOT_LOGIN: ${{ format('{0}[bot]', steps.reviewer.outputs.app-slug) }}
          OPENCODE_GO_API_KEY: ${{ secrets.OPENCODE_GO_API_KEY }}
