# Patched GitHub CLI runtime

Both Action images build gh 2.100.0 from upstream commit
`45437bc7eeeb3359bbfddd1742f79de7652fd3e2` using the digest-pinned Go 1.26.8
builder. The upstream source archive is SHA256-checked before extraction.
`dependencies.patch` changes only `golang.org/x/mod` from 0.39.0 to 0.40.0 and
adds its Go checksum-database-verified module checksums. The build uses
`-mod=readonly` and `GOTOOLCHAIN=local`, so it cannot silently change the
module lock or fetch a different compiler. The installed version is
`2.100.0-mergecraft.1`; its upstream license is retained.

The official 2.100.0 binaries still embed x/mod 0.39.0, affected by
CVE-2026-56864/CVE-2026-56865. A release-version bump alone does not fix those
findings. Retire this patch when a verified upstream binary includes the fixed
module and passes the same image scan and attestation-command checks.

The runtime also pins npm 11.19.1's tarball independently of Node 22. Node's
bundled npm 10 and even npm 10.9.9 retain other vulnerable bundled libraries.
No agent-CLI lockfile dependencies are changed by this tooling update.

Python package installation in these images uses `uv pip` or `uv sync`.
Standalone pip and the `ensurepip` bootstrap are intentionally absent: pip
26.2.1 still vendors msgpack 1.1.2 and setuptools 70.3.0. Their findings are
from the base Python image, not mergeCraft's `uv.lock`. Removing those unused
copies avoids retaining or reintroducing vulnerable code; no scan waiver or
metadata suppression is used. Local CLI installations outside the Action
image are unchanged.

PR image validation builds both images without registry publishing or release
credentials, exercises the installed tools, and scans the actual image.
Release validation retains both Trivy JSON (package/layer attribution) and
SARIF; HIGH/CRITICAL fixed findings still fail the job. Both images are
scanned even when the first image has findings. A passing PR scan does not
prove release signing, attestation, promotion, or consumer-pin acceptance.

## Analyzer image: actionlint runtime

The actual PR image scan additionally found Go stdlib HIGH vulnerabilities in
the official actionlint 1.7.12 binary (Go 1.26.1). The latest upstream release
was still 1.7.12 on 2026-09-08. Dockerfile.analyzers rebuilds unchanged source
`914e7df21a07ef503a81201c76d2b11c789d3fca` with the same pinned Go 1.26.8
toolchain as gh. Its source archive SHA256 is
`30a9b942aa2a9c5246d8434d3ad9ff010969d1d4510281c4d395e18665192e6e`.
The upstream go.mod/go.sum remain unchanged and the build uses `-mod=readonly`.
This affects the shipped analyzer image; the independent CI bootstrap binary
remains separately pinned by scripts/workflow_lint.sh.
