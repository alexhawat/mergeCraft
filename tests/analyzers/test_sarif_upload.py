"""#39 — optional SARIF upload to GitHub code scanning (Batch D, W7).

`export_sarif()` has existed since the catalog landed, and exactly one caller
reaches it: `mergecraft analyzers export --sarif`, an offline CLI command. No
Action run has ever produced a SARIF document, so a consumer whose LLM summary
is thin — or whose findings overflowed the inline noise budget — has no
mechanical surface to read at all. #39 asks for one.

Wiring an existing exporter into the Action path is precisely the shape of
issue #96 (a library implemented, exported, documented and unit-tested while
nothing reachable called it), so these cases pin the *seam* as hard as they pin
the behaviour: `tests/test_runtime_call_sites.py` gains contracts for every
load-bearing function this batch adds.

The upload writes to a permanent, externally-visible surface, so the safety
cases are the point and the plumbing is incidental:

* **off by default** (W7.1, D13) — no flag means no upload *attempt*, not a
  discarded response, and an unrecognised flag value fails closed;
* **validated before upload** (W7.2) — a malformed document is refused loudly
  rather than posted;
* **clustered, budgeted set** (W7.3, D14) — the upload reuses the placed
  finding set, never the raw one;
* **redacted before serialization** (W7.4, convention 8) — a secret-shaped
  string in a message or in evidence never reaches the wire;
* **trust-gated** (W7.5, D13) — on an untrusted run only findings from
  analyzers that selection actually admits at that tier may be uploaded, and
  the gate is the *existing* tier/shell/mode predicate chain, not a fourth
  selection path;
* **non-fatal** (W7.6) — a code-scanning API error is logged and the run still
  completes; SARIF is complementary, never the gate;
* **no raw logs** (W7.7, D13) — CI-sourced findings carry truncated pipeline
  log excerpts in `evidence`; those never enter the document, and `evidence` is
  not serialized at all.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import yaml
from loguru import logger

from mergecraft.analyzers.budget import place_findings
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.redact import assert_no_canary
from mergecraft.analyzers.sarif_upload import (
    build_upload_document,
    encode_sarif_payload,
    redact_findings_for_upload,
    resolve_sarif_upload_enabled,
    select_uploadable_findings,
)
from mergecraft.config.settings import AnalyzersSettings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.code_scanning import report_sarif_upload
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_HEAD_SHA = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
PR_NUMBER = 42

# A GitHub PAT-shaped canary. `redact_secrets()` matches `gh[pousr]_` + 20 or
# more word characters, so this is redacted by pattern and not merely by the
# entropy heuristic — the assertion cannot pass by accident on a lucky score.
TOKEN_CANARY = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class _RecordingGitHub(GitHubClient):
    """Records every REST call instead of reaching the API.

    Records *all* requests, not just code-scanning POSTs: W7.1 asserts that a
    disabled upload makes no request at all, which a sink that only captured
    the final POST could not tell apart from a refused one.
    """

    def __init__(self, *, post_error: Exception | None = None) -> None:
        super().__init__(token="test-token")
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.post_error = post_error

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        self.requests.append(("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}", {}))
        return {"head": {"sha": PR_HEAD_SHA}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        body = kwargs.get("json")
        self.requests.append(("POST", path, body if isinstance(body, dict) else {}))
        if self.post_error is not None:
            raise self.post_error
        return {"id": 1, "url": "https://api.github.com/…/sarifs/1"}

    @property
    def sarif_posts(self) -> list[dict[str, Any]]:
        return [
            body
            for method, path, body in self.requests
            if method == "POST" and path.endswith("/code-scanning/sarifs")
        ]


def _finding(
    *,
    tool: str = "semgrep",
    rule_id: str | None = None,
    message: str = "hardcoded credential in request header",
    path: str = "src/app.py",
    start_line: int = 12,
    severity: str = "Major",
    source: str = "analyzer",
    evidence: list[str] | None = None,
) -> Finding:
    return make_finding(
        tool=tool,
        rule_id=rule_id or f"{tool}:rule-{start_line}",
        category="Security & Privacy",
        severity=severity,
        confidence="likely",
        message=message,
        path=path,
        start_line=start_line,
        end_line=start_line,
        source=source,  # type: ignore[arg-type]
        evidence=evidence or [],
    )


def _run_state(findings: list[Finding]) -> AnalyzerRunState:
    return AnalyzerRunState(
        ran=True,
        analyzers=[
            AnalyzerStatusRow(id=f.tool, status="failed", finding_count=1) for f in findings
        ],
        findings=[f.model_dump() for f in findings],
    )


def _ctx(
    tmp_path: Path,
    *,
    github: _RecordingGitHub | None = None,
    findings: list[Finding] | None = None,
    upload_enabled: bool = True,
    tier: str = "trusted",
    shell: str = "restricted",
    mode: str = "auto",
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.analyzer_run = _run_state(findings if findings is not None else [_finding()])
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=PR_NUMBER, is_pr=True),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=github or _RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        analyzers_mode=mode,  # type: ignore[arg-type]
        trust_tier=tier,  # type: ignore[arg-type]
        sarif_upload_enabled=upload_enabled,
    )


@pytest.fixture
def warnings_sink() -> Iterator[list[str]]:
    """Capture loguru WARNING+ records so "logged, not raised" is assertable."""
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


def _uploaded_documents(github: _RecordingGitHub) -> list[dict[str, Any]]:
    """Decode every uploaded SARIF blob back into a document.

    The wire field is base64-encoded gzip, so searching the request body for a
    canary would pass on any input — including one carrying the secret. Decode
    first, then search; otherwise the redaction assertions are vacuous.
    """
    documents: list[dict[str, Any]] = []
    for body in github.sarif_posts:
        raw = gzip.decompress(base64.b64decode(body["sarif"])).decode("utf-8")
        documents.append(json.loads(raw))
    return documents


def _document_text(github: _RecordingGitHub) -> str:
    """Every byte the upload puts on the wire, decoded into one searchable string."""
    return json.dumps(_uploaded_documents(github))


# --------------------------------------------------------------------------
# W7.1 — opt-in only (D13)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sarif_upload_is_off_by_default(tmp_path: Path) -> None:
    """No flag means no upload *attempt* — not a discarded response (W7.1).

    The distinction matters: an implementation that builds the document, posts
    it and throws the reply away would satisfy a weaker assertion while still
    publishing findings from a repo that never asked for it. Assert on the
    request log, which is empty only if nothing was sent.
    """
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, upload_enabled=False)

    result = await report_sarif_upload(ctx)

    assert result is None
    assert github.requests == [], "upload disabled but requests were made"


def test_default_off_across_every_surface_that_can_enable_it() -> None:
    """The default is off in config, in the ToolContext, and in `action.yml`."""
    assert AnalyzersSettings().sarif_upload is False
    assert ToolContext.__dataclass_fields__["sarif_upload_enabled"].default is False

    action = yaml.safe_load((REPO_ROOT / "action.yml").read_text(encoding="utf-8"))
    spec = action["inputs"]["sarif_upload"]
    assert spec.get("required") is not True
    assert str(spec.get("default", "")).strip().lower() in {"", "disabled", "false"}
    assert action["runs"]["env"]["INPUT_SARIF_UPLOAD"] == "${{ inputs.sarif_upload }}"


@pytest.mark.parametrize(
    ("action_input", "repo_setting", "expected"),
    [
        (None, False, False),
        ("", False, False),
        (None, True, True),
        ("", True, True),
        ("enabled", False, True),
        ("ENABLED", False, True),
        ("disabled", True, False),
        # Convention 5 — ambiguity resolves to the more restrictive outcome,
        # and an operator typo must not silently publish to code scanning.
        ("yes", True, False),
        ("true", True, False),
    ],
    ids=[
        "unset_off",
        "blank_off",
        "unset_defers_to_config",
        "blank_defers_to_config",
        "input_enables",
        "input_case_insensitive",
        "input_disable_wins",
        "unknown_fails_closed",
        "unknown_true_fails_closed",
    ],
)
def test_flag_resolution_defaults_off_and_fails_closed(
    action_input: str | None, repo_setting: bool, expected: bool
) -> None:
    assert (
        resolve_sarif_upload_enabled(action_input=action_input, repo_setting=repo_setting)
        is expected
    )


# --------------------------------------------------------------------------
# W7.2 — validate before upload
# --------------------------------------------------------------------------


def test_build_upload_document_validates_against_the_sarif_schema() -> None:
    document = build_upload_document([_finding()])
    assert document["version"] == "2.1.0"
    assert len(document["runs"][0]["results"]) == 1


@pytest.mark.asyncio
async def test_invalid_document_is_refused_loudly_and_never_uploaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    """An invalid document fails loudly rather than uploading (W7.2)."""
    import mergecraft.analyzers.sarif_upload as upload_mod

    monkeypatch.setattr(upload_mod, "export_sarif", lambda findings: {"version": "1.0"})
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    result = await report_sarif_upload(ctx)

    assert result is None
    assert github.sarif_posts == [], "an invalid SARIF document was uploaded"
    assert any("sarif" in line.lower() for line in warnings_sink), "refusal was silent"


# --------------------------------------------------------------------------
# W7.3 — the clustered, budgeted set (D14)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uploaded_findings_are_the_clustered_budgeted_set(tmp_path: Path) -> None:
    """The upload reads the *placed* set the pipeline stored, not a raw list.

    Two tools reporting the same defect at the same location collapse into one
    cluster, so a correct upload carries fewer results than the raw list. The
    second half of the assertion is just as load-bearing: every placed finding
    is uploaded, inline *and* mechanical. Truncating code scanning at the
    inline budget would throw away exactly the overflow #39 exists to surface.
    """
    raw = [
        _finding(tool="semgrep", rule_id="semgrep:sql-injection", start_line=12),
        _finding(tool="opengrep", rule_id="opengrep:sql-injection", start_line=12),
        *[
            _finding(tool="semgrep", rule_id=f"semgrep:r{n}", start_line=n, path=f"src/m{n}.py")
            for n in range(20, 32)
        ],
    ]
    clustered = cluster_findings(raw)
    placement = place_findings(clustered, inline_budget=3)
    placed_rules = {f.rule_id for f in [*placement.inline, *placement.mechanical]}

    assert len(clustered) < len(raw), "fixture does not exercise clustering"
    assert placement.mechanical, "fixture does not overflow the inline budget"

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, findings=clustered)
    await report_sarif_upload(ctx)

    results = _uploaded_documents(github)[0]["runs"][0]["results"]
    assert len(results) == len(clustered)
    assert len(results) > 3, "upload was truncated at the inline budget"
    assert {row["ruleId"] for row in results} <= placed_rules


# --------------------------------------------------------------------------
# W7.4 — redaction before serialization (convention 8)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("carrier", ["message", "evidence"])
@pytest.mark.asyncio
async def test_upload_is_redacted(tmp_path: Path, carrier: str) -> None:
    """A secret-shaped string never reaches the wire, whichever field holds it.

    Code-scanning alerts are permanent and externally visible, so this is the
    assertion whose silent failure is unrecoverable — the secret is published
    before anyone reads the log.

    Note what each carrier actually proves. `message` is serialized into SARIF,
    so that case fails the moment redaction stops running. `evidence` is *not*
    serialized by `export_sarif()` today, so that case is a forward guard
    against an exporter that starts emitting it — the case that pins evidence
    redaction itself is
    `test_redaction_happens_before_serialization_not_after`, which asserts on
    the typed set.
    """
    if carrier == "message":
        finding = _finding(message=f"leaked credential {TOKEN_CANARY} in header")
    else:
        finding = _finding(evidence=[f"Authorization: Bearer {TOKEN_CANARY}"])

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, findings=[finding])
    await report_sarif_upload(ctx)

    assert github.sarif_posts, "nothing was uploaded — the assertion would be vacuous"
    assert_no_canary(_document_text(github), TOKEN_CANARY)


@pytest.mark.parametrize("carrier", ["message", "evidence", "remediation"])
def test_redaction_happens_before_serialization_not_after(carrier: str) -> None:
    """Redaction is a property of the finding set, not of the encoded blob.

    Asserting only on the encoded payload would pass for an implementation that
    serialized the secret and then string-replaced it, which leaves the secret
    in every intermediate the exporter touched. Pin the typed set instead.
    """
    payload = f"token {TOKEN_CANARY}"
    if carrier == "message":
        finding = _finding(message=payload)
    elif carrier == "evidence":
        finding = _finding(evidence=[payload])
    else:
        finding = _finding().model_copy(update={"remediation": payload})

    redacted = redact_findings_for_upload([finding])

    assert len(redacted) == 1
    assert_no_canary(redacted[0].model_dump_json(), TOKEN_CANARY)
    assert isinstance(redacted[0], Finding), "redaction must preserve the one finding model (D12)"


def test_redaction_does_not_corrupt_the_location(tmp_path: Path) -> None:
    """Paths survive redaction: a mangled `artifactLocation.uri` drops the alert."""
    finding = _finding(path="src/mergecraft/analyzers/sarif_upload.py", start_line=7)
    redacted = redact_findings_for_upload([finding])
    assert redacted[0].path == finding.path
    assert redacted[0].start_line == finding.start_line


# --------------------------------------------------------------------------
# W7.5 — trust gate (D13), routed through the existing predicates
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "shell", "mode", "expected"),
    [
        ("trusted", "restricted", "auto", {"semgrep", "pylint", "ruff", "agentsec"}),
        ("trusted", "restricted", "full", {"semgrep", "pylint", "ruff", "agentsec"}),
        # `pylint` is managed/trusted, `ruff` repo-native/trusted — both drop.
        ("untrusted", "restricted", "auto", {"semgrep", "agentsec"}),
        ("untrusted", "restricted", "full", {"semgrep", "agentsec"}),
        # `shell: disabled` withholds repo-provided tooling; `agentsec` is the
        # documented in-process exception and stays.
        ("trusted", "disabled", "auto", {"semgrep", "pylint", "agentsec"}),
        ("untrusted", "disabled", "auto", {"semgrep", "agentsec"}),
        # The mode axis narrows on an otherwise-trusted run.
        ("trusted", "restricted", "untrusted-only", {"semgrep", "agentsec"}),
    ],
    ids=[
        "trusted_auto",
        "trusted_full",
        "untrusted_auto",
        "untrusted_full",
        "trusted_shell_disabled",
        "untrusted_shell_disabled",
        "trusted_untrusted_only",
    ],
)
def test_untrusted_tier_upload_scope(tier: str, shell: str, mode: str, expected: set[str]) -> None:
    """Only findings selection admits at this tier/shell/mode may be uploaded.

    The expected sets are restated from the policy, not read back off the
    predicates, so a predicate that stopped skipping would fail here rather
    than quietly agree with itself.
    """
    findings = [_finding(tool=tool) for tool in ("semgrep", "pylint", "ruff", "agentsec")]

    selected = select_uploadable_findings(findings, tier=tier, shell=shell, mode=mode)  # type: ignore[arg-type]

    assert {f.tool for f in selected} == expected


def test_upload_scope_reuses_the_pipeline_predicates_not_a_fourth_path() -> None:
    """The gate agrees with the pipeline's own skip chain, manifest by manifest.

    Batch B added `cause` to `evaluate_manifest_for_tier()` rather than a
    second skip vocabulary; the same discipline applies here. This sweeps the
    whole catalog so a divergent copy of the policy shows up as a disagreement
    rather than as a plausible-looking allowlist.
    """
    from mergecraft.analyzers.registry import load_catalog
    from mergecraft.analyzers.trust import (
        evaluate_manifest_for_mode,
        evaluate_manifest_for_shell,
        evaluate_manifest_for_tier,
        resolve_effective_analyzers_mode,
        resolve_selection_tier,
    )

    manifests = sorted(load_catalog(), key=lambda m: m.id)
    for tier in ("trusted", "untrusted"):
        for shell in ("restricted", "disabled"):
            for mode in ("auto", "full", "untrusted-only"):
                effective = resolve_effective_analyzers_mode(mode=mode, tier=tier)  # type: ignore[arg-type]
                selection_tier = resolve_selection_tier(mode=effective, tier=tier)  # type: ignore[arg-type]
                expected = {
                    m.id
                    for m in manifests
                    if not evaluate_manifest_for_tier(manifest=m, tier=selection_tier).skipped
                    and not evaluate_manifest_for_shell(manifest=m, shell=shell).skipped
                    and not evaluate_manifest_for_mode(manifest=m, mode=effective).skipped
                }
                findings = [_finding(tool=m.id) for m in manifests]
                selected = select_uploadable_findings(
                    findings,
                    tier=tier,  # type: ignore[arg-type]
                    shell=shell,
                    mode=mode,  # type: ignore[arg-type]
                )
                assert {f.tool for f in selected} == expected, (
                    f"upload gate disagrees with the pipeline at "
                    f"tier={tier} shell={shell} mode={mode}"
                )


def test_findings_from_unknown_tools_are_not_uploaded() -> None:
    """A tool with no manifest cannot be trust-gated, so it is not uploaded."""
    selected = select_uploadable_findings(
        [_finding(tool="not-a-catalog-analyzer")],
        tier="trusted",
        shell="restricted",
        mode="auto",
    )
    assert selected == []


# --------------------------------------------------------------------------
# W7.6 — upload failure is never the gate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        httpx.HTTPStatusError(
            "403 Forbidden",
            request=httpx.Request("POST", "https://api.github.com"),
            response=httpx.Response(403),
        ),
        httpx.ConnectError("connection refused"),
        RuntimeError("boom"),
    ],
    ids=["forbidden", "transport", "unexpected"],
)
@pytest.mark.asyncio
async def test_upload_failure_does_not_fail_the_run(
    tmp_path: Path, error: Exception, warnings_sink: list[str]
) -> None:
    """A code-scanning error is logged at warning and the run still completes.

    `security-events: write` is missing from most workflows and code scanning
    is unavailable on private repos without Advanced Security, so 403 is the
    *expected* response for a large share of consumers. If that failed the run,
    an opt-in complementary surface would become a merge blocker.
    """
    github = _RecordingGitHub(post_error=error)
    ctx = _ctx(tmp_path, github=github)

    result = await report_sarif_upload(ctx)

    assert result is None
    assert warnings_sink, "upload failure was swallowed silently"


@pytest.mark.asyncio
async def test_upload_is_skipped_when_the_run_produced_no_findings(tmp_path: Path) -> None:
    """Nothing to publish means no request — an empty SARIF run is not signal."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, findings=[])

    assert await report_sarif_upload(ctx) is None
    assert github.sarif_posts == []


# --------------------------------------------------------------------------
# W7.7 — no raw logs (D13)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_raw_logs_uploaded(tmp_path: Path) -> None:
    """CI-sourced findings carry pipeline log excerpts; they never leave here.

    Batch C's `ci_evidence_lines()` truncates and redacts a log excerpt into
    `Finding.evidence` so the *reviewing agent* can read it. Code scanning is a
    different audience and a permanent one: D13 says never upload log excerpts
    wholesale, and #39 scopes the surface to catalog analyzers. So a `source`
    of `ci` or `agent` is excluded outright, and `evidence` is not serialized
    on any finding.

    The CI rows deliberately use a **catalog** `tool` id (`semgrep`). Batch C
    namespaces its own CI findings `ci:<artifact>`, which the upload gate would
    drop anyway as an unknown analyzer — so a fixture using that shape would
    pass even with the source filter deleted, and would prove nothing about the
    filter this case exists to pin. `tool` is a free string on `Finding`;
    isolating the `source` check is the point.
    """
    log_excerpt = [
        f"2026-08-10T09:14:02Z build#941 export GH_TOKEN={TOKEN_CANARY}",
        "2026-08-10T09:14:03Z build#941 make: *** [test] Error 1",
    ]
    findings = [
        _finding(tool="semgrep", message="clean analyzer finding"),
        _finding(
            tool="semgrep",
            rule_id="semgrep:from-ci",
            source="ci",
            message="reported by the consumer's own pipeline",
            evidence=log_excerpt,
        ),
        _finding(tool="semgrep", rule_id="agent:review", source="agent", message="narrative"),
    ]
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, findings=findings)

    await report_sarif_upload(ctx)

    wire = _document_text(github)
    assert github.sarif_posts, "nothing was uploaded — the assertion would be vacuous"
    assert_no_canary(wire, TOKEN_CANARY)
    assert "Error 1" not in wire, "a raw CI log line reached the upload"
    assert "narrative" not in wire, "an agent narrative finding reached the upload"
    assert "evidence" not in wire, "the evidence field was serialized into SARIF"


@pytest.mark.parametrize("source", ["ci", "agent"])
def test_only_analyzer_sourced_findings_are_uploadable(source: str) -> None:
    """#39 scopes the surface to catalog analyzers; other sources drop.

    `tool` is a real catalog id here so the assertion turns on `source` alone —
    an unknown-tool fixture would be dropped by a different guard entirely.
    """
    selected = select_uploadable_findings(
        [_finding(tool="semgrep", source=source)],
        tier="trusted",
        shell="restricted",
        mode="auto",
    )
    assert selected == []


# --------------------------------------------------------------------------
# Wire shape — the upload has to be something code scanning accepts
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_targets_the_code_scanning_endpoint_for_the_pr_head(tmp_path: Path) -> None:
    """The POST names the code-scanning SARIF endpoint, the PR head, and its ref."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    await report_sarif_upload(ctx)

    posts = [
        (path, body)
        for method, path, body in github.requests
        if method == "POST" and path.endswith("/code-scanning/sarifs")
    ]
    assert len(posts) == 1
    path, body = posts[0]
    assert path == "/repos/acme/demo/code-scanning/sarifs"
    assert body["commit_sha"] == PR_HEAD_SHA
    assert body["ref"] == f"refs/pull/{PR_NUMBER}/head"
    assert isinstance(body["sarif"], str)
    assert body["sarif"]


def test_encoded_payload_round_trips() -> None:
    """`sarif` is base64-encoded gzip, which is the only shape GitHub accepts."""
    import base64
    import gzip

    document = build_upload_document([_finding()])
    encoded = encode_sarif_payload(document)
    assert json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8")) == document


@pytest.mark.asyncio
async def test_upload_is_skipped_when_the_event_has_no_pull_request(tmp_path: Path) -> None:
    """Code-scanning results are diff-scoped; with no PR there is nothing to attach."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    ctx.payload.event.is_pr = False
    ctx.payload.event.issue_number = None

    assert await report_sarif_upload(ctx) is None
    assert github.sarif_posts == []


# --------------------------------------------------------------------------
# Docs / template — opt-in stays visibly opt-in
# --------------------------------------------------------------------------


def test_hardened_example_documents_the_flag_without_enabling_it() -> None:
    """The hardened template shows how to opt in, and does not opt in.

    Enabling it there would contradict D13's "with the flag unset nothing
    changes" acceptance criterion for every consumer who copies the template.
    """
    rendered = (REPO_ROOT / "examples" / "workflows" / "mergecraft-hardened.yml").read_text(
        encoding="utf-8"
    )
    template = (REPO_ROOT / "scripts" / "example_workflows" / "hardened.yml.tpl").read_text(
        encoding="utf-8"
    )

    for text in (rendered, template):
        assert "sarif_upload" in text, "the template does not mention the opt-in flag"
        assert "security-events: write" in text, "the required permission is undocumented"
        # Both the flag and the permission must be commented out.
        active = [
            line
            for line in text.splitlines()
            if line.strip().startswith(("sarif_upload:", "security-events:"))
        ]
        assert not active, f"the hardened example enables SARIF upload: {active}"

    workflow = yaml.safe_load(rendered)
    assert "security-events" not in workflow["permissions"]


def test_readme_documents_the_permission_and_the_flag() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "sarif_upload" in readme
    assert "security-events: write" in readme


def test_analyzers_doc_is_generated_with_the_sarif_section() -> None:
    """`docs/ANALYZERS.md` is fully generated — the section lives in the generator."""
    from mergecraft.analyzers.catalog_docs import generate_analyzers_doc

    generated = generate_analyzers_doc()
    assert "code scanning" in generated.lower()
    assert "security-events: write" in generated
    assert generated == (REPO_ROOT / "docs" / "ANALYZERS.md").read_text(encoding="utf-8")
