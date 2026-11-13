# CLI harness attempt runner

Claude Code, Codex, Gemini, and OpenCode's streaming `run` path use
`agents/cli_runner.py`. Each driver supplies a `CliHarnessSpec`: its command,
restricted environment, prompt input, event handler, usage adapter, and result
classifier. Provider-specific session identifiers, sandbox diagnostics,
subscription failures, and cost attribution stay in the driver.

`run_cli_attempt` starts the process in the review checkout through
`spawn_agent_cli`, drains stderr concurrently, watches idle and wall-clock
limits, and closes streaming spans. Timeout results retain observed usage and
remain eligible for retry. A stream reader exception kills and reaps the child
before it propagates. OpenCode's version probe and server boot also use the
shared spawn helper, preserving privilege dropping and review identity; the
version probe receives a filtered environment without provider credentials.

The surrounding lifecycle remains shared: `AgentImpl.run` owns cancellation
scopes, the checkout integrity gate for local CLI drivers, and run-budget
accounting. OpenCode retains its attempt-level integrity checks. The
`post_run` retry loop owns resumable follow-up policy. Provider environment
builders keep their existing homes and credential refresh rules;
a resume turn uses the same home and session as its initial turn.

The agent suite exercises every backend's checkout, success/failure/timeout
usage, deadlines, stderr flooding, process cleanup, and failover classification.
Run the suite through `make test`.
