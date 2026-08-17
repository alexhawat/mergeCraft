# Security test fixtures

## hostile-repo (TS5)

Adversarial git corpus for `tests/security/test_hostile_corpus.py`. Combines
executable config attacks, symlink escape, prompt injection, oversized blobs,
and trust-escalation snippets from the CLI sources trust wave plan.

Build (or rebuild) on demand:

```bash
tests/security/fixtures/build_hostile_repo.sh
```

`make test` auto-builds the corpus when missing via `require_hostile_repo()`.
