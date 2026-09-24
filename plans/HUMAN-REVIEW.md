# Human adjudication review sheet: golden-batch-001

Adjudicator: `alexhawat`

This sheet records no severity because `CorpusCase` has no severity field.
Every UNANSWERED row requires an explicit `confirm`, `correct`, or `abstain` response.

| Case ID | Claimed title | Claimed path/range | Category | Evidence | Decision |
|---|---|---|---|---|---|
| golden-go-chi-api-breakage-001 | Exported handler signature drop breaks downstream clients | pkg/api/handlers.go:90-110 | api_breakage | missing | abstain by alexhawat |
| golden-java-spring-performance-001 | N+1 repository call inside a request mapping | src/main/java/com/example/OrderService.java:120-160 | performance | missing | abstain by alexhawat |
| golden-javascript-npm-dependency-001 | Direct dependency pin removed while lockfile still resolves it | package.json:12-40 | dependency | missing | abstain by alexhawat |
| golden-python-django-migration-001 | Destructive column drop without a expand/contract step | app/migrations/0042_drop_legacy_slug.py:1-24 | migration | missing | abstain by alexhawat |
| golden-python-fastapi-correctness-001 | Optional nested config dereference without a null guard | app/settings.py:44-48 | correctness | missing | abstain by alexhawat |
| golden-python-requirements-001 | Ticket requires authz check that the diff never adds | docs/tickets/AUTHZ-19.md:1-30 | correctness | missing | abstain by alexhawat |
| golden-ruby-rails-clean-001 | Docs-only README wording with no behavioural diff | README.md:1-12 | clean | missing | abstain by alexhawat |
| golden-rust-tokio-concurrency-001 | Shared HashMap mutated across tasks without a lock | src/cache.rs:55-80 | concurrency | missing | abstain by alexhawat |
| golden-typescript-express-security-001 | Unparameterized SQL concatenated from a request query | src/routes/search.ts:18-26 | security | missing | abstain by alexhawat |
