# mergeCraft evals

ReviewBench-style benchmark infrastructure for mergecraft PR reviews.

## Status

The frozen task corpus is **not** checked in here yet. Task definitions, patches, and
expected-finding labels live in companion work tracked at
[sevn-bot/tripll#64](https://github.com/sevn-bot/tripll/issues/64).

When tripll delivers a minimal frozen slice, add tasks under `evals/reviewbench/` and
run benchmarks with:

```bash
make bench-review
```

## Harbor agent

Batch B ships a Harbor agent at `mergecraft.harbor.agent:MergecraftReviewAgent`.
Install the optional extra and invoke via Harbor:

```bash
uv sync --extra harbor
harbor run -d "<dataset>" --agent mergecraft.harbor.agent:MergecraftReviewAgent
```

The agent installs mergecraft with `uv tool install git+https://github.com/alexhawat/mergeCraft@<ref>`
(default ref `pre-0.0.1`; override with `MERGECRAFT_INSTALL_REF`) and runs
`mergecraft diff-review --json` inside each task environment.

Structured JSON output requires Batch A (`--json` on `diff-review`) — see
[mergeCraft#30](https://github.com/alexhawat/mergeCraft/issues/30).
