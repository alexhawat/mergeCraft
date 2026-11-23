# Batch 001 review sheet

All nine original claims are pending. The earlier attribution was withdrawn at the intended reviewer’s request. To confirm or correct a claim, supply its original PR, commit-pinned file, or archived patch.

| Case | Proposed finding | Claimed location | Evidence | Decision |
| --- | --- | --- | --- | --- |
| `golden-go-chi-api-breakage-001` | Exported handler signature drop breaks downstream clients | `pkg/api/handlers.go:90-110` | Missing | Pending |
| `golden-java-spring-performance-001` | N+1 repository call inside a request mapping | `src/main/java/com/example/OrderService.java:120-160` | Missing | Pending |
| `golden-javascript-npm-dependency-001` | Direct dependency pin removed while lockfile still resolves it | `package.json:12-40` | Missing | Pending |
| `golden-python-django-migration-001` | Destructive column drop without a expand/contract step | `app/migrations/0042_drop_legacy_slug.py:1-24` | Missing | Pending |
| `golden-python-fastapi-correctness-001` | Optional nested config dereference without a null guard | `app/settings.py:44-48` | Missing | Pending |
| `golden-python-requirements-001` | Ticket requires authz check that the diff never adds | `docs/tickets/AUTHZ-19.md:1-30` | Missing | Pending |
| `golden-ruby-rails-clean-001` | Docs-only README wording with no behavioural diff | `README.md:1-12` | Missing | Pending |
| `golden-rust-tokio-concurrency-001` | Shared HashMap mutated across tasks without a lock | `src/cache.rs:55-80` | Missing | Pending |
| `golden-typescript-express-security-001` | Unparameterized SQL concatenated from a request query | `src/routes/search.ts:18-26` | Missing | Pending |
