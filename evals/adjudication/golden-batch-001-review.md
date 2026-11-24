# Batch 001 review sheet

Batch 001 will not be adjudicated. The maintainer closed [#780](https://github.com/alexhawat/mergeCraft/issues/780) as not planned on 2026-11-23, and none of the nine claims has source evidence. The earlier attribution was withdrawn at the intended reviewer’s request on 2026-11-19, and no decision is recorded. This sheet is kept as a record of the original claims; the Decision column mirrors the manifest and no row is awaiting an answer.

The candidates awaiting decisions are in the [batch 002 review packet](golden-batch-002-review.md).

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
