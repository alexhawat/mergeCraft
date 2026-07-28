# Analyzer platform fixture repo

Deliberately planted findings for adapter and catalog waves. Paths are relative to this directory.

| Planted finding | Path | Target wave |
|---|---|---|
| Broken GitHub workflow (invalid `on:` key) | `.github/workflows/broken.yml` | W6 actionlint |
| Unpinned third-party action (`@main`) | `.github/workflows/unpinned-action.yml` | W6 zizmor |
| Unquoted shell variable | `scripts/deploy.sh` | W6 ShellCheck |
| `FROM …:latest` Dockerfile tag | `Dockerfile` | W6 Hadolint |
| Vulnerable pinned dependency (`requests==2.25.0`) | `requirements.txt` | Catalog C2 (OSV/Trivy) |
| Canary fake secret (D8 escape test) | `.env.example` | W4 redaction / W6+ |
| Lock-heavy SQL migration (unsafe DDL) | `db/migrations/001_add_users.sql` | Catalog C4 Squawk |
| Breaking OpenAPI change (removed field) | `openapi/v1.yaml` + `openapi/v1.base.yaml` | Catalog C4 oasdiff |
| MCP manifest exfiltration instruction | `.mergecraft/mcp-servers/evil-server.yaml` | Catalog C5 agent-security |
| Python type error (`str + int`) | `src/fixture_app/handler.py` | Catalog C1 mypy/pyright |
| Ruff unused binding | `src/fixture_app/handler.py` | Catalog C1 ruff |
| ESLint `no-unused-vars` (config-dependent) | `src/index.js` + `.eslintrc.json` | Catalog C1 ESLint |
| Newly introduced CVE (base vs head) | `requirements.base.txt` → `requirements.txt` | Catalog C2 OSV/Trivy |
| Planted AWS secret (rotation-first) | `config/planted-secret.env` | Catalog C2 TruffleHog |
| Taint-style `eval` sink | `src/fixture_app/eval_sink.py` | Catalog C3 Semgrep/ast-grep |
| Breaking proto field removal | `proto/user/v1/user.proto` + `user.base.proto` | Catalog C4 buf breaking |
| Injection-shaped skill instruction | `.cursor/rules/exfil-skill.md` | Catalog C5 agent-security |

Do not “fix” these issues — they exist to prove detection.
