# Analyzer catalog

Shipped mergeCraft catalog analyzers. Rows are generated from manifests — run ``uv run python -m mergecraft.analyzers.catalog_docs`` to refresh.

| id | category | languages | default | runtime | trust | exclusive group | notes |
|----|----------|-----------|---------|---------|-------|-----------------|-------|
| `actionlint` | ci | — | auto | managed | untrusted | — | — |
| `agentsec` | security | — | enabled | repo-native | untrusted | — | — |
| `ast-grep` | security | python, javascript, typescript, go, java, rust, c, cpp | auto | managed | untrusted | pattern-scanner | Substrate for a future native policy engine — not built in C3. |
| `basedpyright` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `biome` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `blinter` | lint | batch | disabled | managed | trusted | — | requires non-Linux runner — Windows batch lint not supported on Linux (C6) |
| `brakeman` | security | ruby | disabled | repo-native | trusted | — | — |
| `buf` | contract | — | auto | managed | untrusted | — | — |
| `checkmake` | lint | make | disabled | managed | trusted | — | — |
| `checkov` | security | terraform, cloudformation | disabled | managed | untrusted | iac-scanner | — |
| `circleci` | lint | yaml | disabled | managed | untrusted | — | — |
| `clang-tidy` | lint | c, cpp | disabled | container | trusted | — | requires compile_commands.json — mergeCraft never guesses compiler flags (C4) |
| `clippy` | lint | rust | disabled | repo-native | trusted | rust-lint | — |
| `cppcheck` | lint | c, cpp | disabled | managed | trusted | — | — |
| `detekt` | lint | kotlin | disabled | repo-native | trusted | — | — |
| `dotenv-linter` | lint | — | disabled | managed | trusted | — | Values never printed in findings (D8). |
| `ember-template-lint` | lint | ember | disabled | repo-native | trusted | — | — |
| `eslint` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `flake8` | lint | python | disabled | repo-native | trusted | python-lint | — |
| `fortitude` | lint | fortran | disabled | managed | trusted | — | manifest-only — Fortitude not bundled on Linux runners (C6 out of scope) |
| `golangci-lint` | lint | go | disabled | managed | trusted | go-lint | — |
| `hadolint` | lint | docker | auto | managed | untrusted | — | — |
| `htmlhint` | lint | html | disabled | repo-native | trusted | — | — |
| `infer` | security | java, c, cpp | disabled | container | trusted | — | requires compilation database and build — container-only heavyweight (C4) |
| `languagetool` | lint | text | disabled | container | trusted | — | manifest-only — LanguageTool runtime not bundled on Linux runners (C6 out of scope) |
| `luacheck` | lint | lua | disabled | repo-native | trusted | — | — |
| `markdownlint` | lint | markdown | disabled | repo-native | trusted | — | — |
| `mypy` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `oasdiff` | contract | — | auto | managed | untrusted | — | — |
| `opengrep` | security | python, javascript, typescript, go, java, ruby, rust | disabled | managed | untrusted | pattern-scanner | — |
| `osv-scanner` | vuln | — | auto | managed | untrusted | dependency-vuln | — |
| `oxlint` | lint | javascript, typescript | auto | repo-native | trusted | js-lint | — |
| `phpcs` | lint | php | disabled | repo-native | trusted | php-lint | — |
| `phpmd` | lint | php | disabled | repo-native | trusted | — | — |
| `phpstan` | lint | php | disabled | repo-native | trusted | — | — |
| `pmd` | lint | java | disabled | managed | trusted | — | — |
| `presidio` | security | — | disabled | container | trusted | — | Container-only; high-confidence entity types only. |
| `prisma-lint` | lint | prisma | disabled | repo-native | trusted | — | — |
| `psscriptanalyzer` | lint | powershell | disabled | managed | trusted | — | requires non-Linux runner — Windows/macOS only (C6 out of scope) |
| `pylint` | lint | python | disabled | managed | trusted | python-lint | — |
| `pyright` | lint | python | auto | repo-native | trusted | python-typecheck | — |
| `regal` | lint | rego | disabled | managed | trusted | — | — |
| `rubocop` | lint | ruby | disabled | repo-native | trusted | ruby-lint | — |
| `ruff` | lint | python | auto | repo-native | trusted | python-lint | — |
| `semgrep` | security | python, javascript, typescript, go, java, ruby, rust | enabled | managed | untrusted | pattern-scanner | — |
| `shellcheck` | lint | shell | auto | managed | untrusted | — | — |
| `shopify-theme-check` | lint | liquid | disabled | repo-native | trusted | — | manifest-only — Shopify Theme Check not bundled on Linux runners (C6 out of scope) |
| `smarty-lint` | lint | smarty | disabled | repo-native | trusted | — | manifest-only — Smarty Lint not bundled on Linux runners (C6 out of scope) |
| `sqlfluff` | lint | sql | disabled | managed | trusted | — | Dialect is mandatory — skip when repo declares none. |
| `squawk` | migration | — | auto | managed | untrusted | — | — |
| `stylelint` | lint | css | disabled | repo-native | trusted | — | — |
| `swiftlint` | lint | swift | disabled | managed | trusted | — | requires non-Linux runner — SwiftLint needs macOS (C6 out of scope) |
| `tflint` | lint | terraform | disabled | managed | untrusted | iac-scanner | — |
| `trivy` | vuln | — | auto | managed | untrusted | dependency-vuln | — |
| `trufflehog` | secrets | — | auto | managed | untrusted | — | verify off by default; impossible on fork PRs (C2). |
| `yamllint` | lint | yaml | disabled | managed | untrusted | — | — |
| `zizmor` | ci | — | auto | managed | untrusted | — | — |

## Overrides

Enable or disable tools in ``.mergecraft/config.yaml``:

```yaml
analyzers:
  overrides:
    golangci-lint:
      enabled: true
```

See [CONTRIBUTING-ANALYZERS.md](CONTRIBUTING-ANALYZERS.md) to add a tool.
