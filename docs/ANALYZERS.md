# Analyzer catalog

Generated reference for shipped catalog analyzers. Full catalog enforcement lands in C6.

| id | category | default | exclusive group | notes |
|----|----------|---------|-----------------|-------|
| semgrep | security | enabled | pattern-scanner | Repo `.semgrep.yml` / `.semgrep/` wins; otherwise `mergecraft-conservative-security` bundled rules (named in review). |
| opengrep | security | disabled | pattern-scanner | Swappable Semgrep-family backend via `analyzers.pattern.backend: opengrep`. |
| ast-grep | security | auto | pattern-scanner | Honors repo `sgconfig.yml` and rule dirs. Also intended as the substrate for a future native policy engine — not built in C3. |

## Pattern backend selection

Set in `.mergecraft/config.yaml`:

```yaml
analyzers:
  pattern:
    backend: semgrep  # or opengrep
```

Exactly one member of `pattern-scanner` runs per diff (D13/C1). Critical/Major taint-style hits route to `mergecraft-verifier` before review (D11).
