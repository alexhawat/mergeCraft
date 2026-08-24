"""Shared helpers for BA #477 provider-registry CLI tests."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

PROVIDER_CMD_MODULE = "mergecraft.cli.provider_cmd"
MODEL_CMD_MODULE = "mergecraft.cli.model_cmd"
PROVIDER_REGISTRY_MODULE = "mergecraft.config.provider_registry"
MODEL_REGISTRY_MODULE = "mergecraft.config.model_registry"

BUILTIN_HARNESS_DEFAULTS: dict[str, str] = {
    "openai": "codex",
    "anthropic": "claude",
    "google": "gemini",
    "cursor": "cursor",
}

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
CUSTOM_BASE_URL = "https://gateway.example.invalid/v1"
EXPECTED_BUILTIN_PROVIDER_COUNT = 14

# BB #478 — unified ``provider auth`` contracts (D6-D7, D10).

AUTH_KIND_API_KEY = "api_key"
AUTH_KIND_OAUTH = "oauth"
AUTH_KIND_DEVICE_CODE = "device_code"
AUTH_KIND_CLOUD_CHAIN = "cloud_chain"

LEGACY_AUTH_SUBCOMMANDS: tuple[str, ...] = (
    "codex",
    "claude",
    "gemini",
    "cursor",
    "nous",
    "tokenhub",
    "minimax",
)

AUTH_KIND_PRIMARY_SUFFIX: dict[str, str] = {
    AUTH_KIND_API_KEY: "API_KEY",
    AUTH_KIND_OAUTH: "CLAUDE_CODE_OAUTH_TOKEN",
    AUTH_KIND_DEVICE_CODE: "CODEX_AUTH_JSON",
}

BEDROCK_INDEXED_KEYS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

VERTEX_INDEXED_KEYS: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)

EXPECTED_SEEDED_AUTH_KINDS: dict[str, str] = {
    "openai": AUTH_KIND_DEVICE_CODE,
    "anthropic": AUTH_KIND_OAUTH,
    "google": AUTH_KIND_API_KEY,
    "cursor": AUTH_KIND_API_KEY,
    "nous": AUTH_KIND_API_KEY,
    "tokenhub": AUTH_KIND_API_KEY,
    "minimax": AUTH_KIND_API_KEY,
    "bedrock": AUTH_KIND_CLOUD_CHAIN,
    "vertex": AUTH_KIND_CLOUD_CHAIN,
}


def import_provider_cmd() -> Any:
    """Import ``mergecraft.cli.provider_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(PROVIDER_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{PROVIDER_CMD_MODULE} is not implemented yet: {exc}")


def import_provider_registry() -> Any:
    """Import ``mergecraft.config.provider_registry`` or fail with a clear message."""
    try:
        return importlib.import_module(PROVIDER_REGISTRY_MODULE)
    except ImportError as exc:
        pytest.fail(f"{PROVIDER_REGISTRY_MODULE} is not implemented yet: {exc}")


def import_model_cmd() -> Any:
    """Import ``mergecraft.cli.model_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(MODEL_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{MODEL_CMD_MODULE} is not implemented yet: {exc}")


def import_model_registry() -> Any:
    """Import ``mergecraft.config.model_registry`` or fail with a clear message."""
    try:
        return importlib.import_module(MODEL_REGISTRY_MODULE)
    except ImportError as exc:
        pytest.fail(f"{MODEL_REGISTRY_MODULE} is not implemented yet: {exc}")


def scaffold_mergecraft_home(tmp_path: Path, *, config_body: str = "") -> Path:
    """Create ``.mergecraft/config.yaml`` under *tmp_path* and return the config path."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    if path.is_file():
        return path
    body = config_body.strip()
    path.write_text((body + "\n") if body else "models: []\n", encoding="utf-8")
    return path


def read_config(tmp_path: Path) -> dict[str, Any]:
    """Load ``.mergecraft/config.yaml`` as a dict."""
    path = tmp_path / ".mergecraft" / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def read_env_file(tmp_path: Path) -> dict[str, str]:
    """Parse ``.env`` key/value pairs (simple ``KEY=value`` lines only)."""
    path = tmp_path / ".env"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def provider_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the ``providers`` list from a config dict."""
    providers = config.get("providers")
    if providers is None:
        return []
    assert isinstance(providers, list)
    return [entry for entry in providers if isinstance(entry, dict)]


def indexed_env_key(env_index: int, suffix: str) -> str:
    """Return ``LLM_PROVIDER_<N>_<SUFFIX>`` per #478."""
    return f"LLM_PROVIDER_{env_index}_{suffix}"


def write_provider_entry(
    tmp_path: Path,
    *,
    label: str,
    env_index: int,
    harness: str = "opencode",
    auth_kind: str = AUTH_KIND_API_KEY,
    url: str | None = None,
) -> None:
    """Append one provider row to ``.mergecraft/config.yaml`` (BB auth fixtures)."""
    config = read_config(tmp_path)
    entries = provider_entries(config)
    entry: dict[str, Any] = {
        "label": label,
        "harness": harness,
        "envIndex": env_index,
        "authKind": auth_kind,
    }
    if url is not None:
        entry["url"] = url
    entries.append(entry)
    config["providers"] = entries
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def require_provider_auth_symbols() -> Any:
    """Import ``provider_cmd`` and require BB auth helpers to exist."""
    module = import_provider_cmd()
    for name in (
        "indexed_credential_keys",
        "resolve_auth_strategy",
        "provider_auth_cmd",
    ):
        if not hasattr(module, name):
            pytest.fail(f"{PROVIDER_CMD_MODULE}.{name} is not implemented")
    return module


def provider_entry(config: dict[str, Any], label: str) -> dict[str, Any] | None:
    """Return the provider registry row for *label*, if present."""
    lowered = label.strip().lower()
    for entry in provider_entries(config):
        if str(entry.get("label", "")).lower() == lowered:
            return entry
    return None


def provider_model_entries(config: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Return model rows under the provider *label* in config."""
    entry = provider_entry(config, label)
    if entry is None:
        return []
    models = entry.get("models")
    if models is None:
        return []
    assert isinstance(models, list)
    return [row for row in models if isinstance(row, dict)]


def model_id_value(row: dict[str, Any]) -> str:
    """Extract the stored model id from a config model row."""
    for key in ("id", "modelId", "model"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return ""


def model_index_value(row: dict[str, Any]) -> int | None:
    """Extract ``modelIndex`` from a config model row."""
    raw = row.get("modelIndex")
    if raw is None:
        return None
    return int(raw)


# BD #480 — ``agents setmodel`` / ``addbackupmodel`` fixtures (D8).

AGENTS_CMD_MODULE = "mergecraft.cli.agents_cmd"


def import_agents_cmd() -> Any:
    """Import ``mergecraft.cli.agents_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(AGENTS_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{AGENTS_CMD_MODULE} is not importable: {exc}")


def format_model_slug(provider_label: str, model_id: str) -> str:
    """Return ``provider/model`` slug for agent ``modelChain`` entries (#480)."""
    return f"{provider_label.strip().lower()}/{model_id}"


def agents_block(config: dict[str, Any]) -> dict[str, Any]:
    """Return the ``agents`` mapping from a config dict."""
    agents = config.get("agents")
    if agents is None:
        return {}
    assert isinstance(agents, dict)
    return agents


def agents_model_chain(config: dict[str, Any], role: str) -> list[str]:
    """Return ``modelChain`` for one agent role from raw config."""
    entry = agents_block(config).get(role.lower(), {})
    if not isinstance(entry, dict):
        return []
    chain = entry.get("modelChain")
    if chain is None:
        return []
    assert isinstance(chain, list)
    return [str(item) for item in chain]


def write_agents_model_chain(tmp_path: Path, role: str, chain: list[str]) -> None:
    """Persist ``agents.<role>.modelChain`` in ``.mergecraft/config.yaml``."""
    config = read_config(tmp_path)
    agents = config.setdefault("agents", {})
    if not isinstance(agents, dict):
        pytest.fail("agents block must be a mapping")
    entry = agents.setdefault(role.lower(), {})
    if not isinstance(entry, dict):
        pytest.fail(f"agents.{role} must be a mapping")
    entry["modelChain"] = list(chain)
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


# BE #481 — registry-only provider runtime (drop Nous/TokenHub/MiniMax presets).

LEGACY_GATEWAY_ENV_KEYS: tuple[str, ...] = (
    "NOUS_API_KEY",
    "NOUS_BASE_URL",
    "TOKENHUB_API_KEY",
    "TOKENHUB_BASE_URL",
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
)

REMOVED_GATEWAY_PRESET_LABELS: frozenset[str] = frozenset({"nous", "tokenhub", "minimax"})

REMOVED_GATEWAY_MODULE_SYMBOLS: tuple[str, ...] = (
    "DEFAULT_NOUS_BASE_URL",
    "NOUS_API_KEY_ENV",
    "NOUS_BASE_URL_ENV",
    "DEFAULT_TOKENHUB_BASE_URL",
    "TOKENHUB_API_KEY_ENV",
    "TOKENHUB_BASE_URL_ENV",
    "DEFAULT_MINIMAX_BASE_URL",
    "MINIMAX_API_KEY_ENV",
    "MINIMAX_BASE_URL_ENV",
)

NOUS_TENCENT_HY3 = "tencent/hy3"
NOUS_DEEPSEEK_V4 = "deepseek/deepseek-v4-flash"
CUSTOM_REGISTRY_URL = "https://registry-acme.example.invalid/v1"


def clear_legacy_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset preset and singleton custom-provider env vars (BE #481)."""
    for key in LEGACY_GATEWAY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for index in range(1, 8):
        monkeypatch.delenv(f"LLM_PROVIDER_{index}", raising=False)
        monkeypatch.delenv(f"LLM_PROVIDER_{index}_API_KEY", raising=False)


def write_registry_provider_row(
    tmp_path: Path,
    *,
    label: str,
    harness: str,
    env_index: int,
    url: str | None = None,
    models: list[dict[str, object]] | None = None,
    auth_kind: str | None = None,
) -> None:
    """Append one ``providers:`` row for agent-resolve registry tests."""
    config = read_config(tmp_path)
    entries = provider_entries(config)
    row: dict[str, object] = {
        "label": label,
        "harness": harness,
        "envIndex": env_index,
        "authKind": auth_kind or AUTH_KIND_API_KEY,
    }
    if url is not None:
        row["url"] = url
    if models is not None:
        row["models"] = models
    entries.append(row)
    config["providers"] = entries
    path = tmp_path / ".mergecraft" / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def write_indexed_provider_secret(
    tmp_path: Path,
    *,
    env_index: int,
    label: str,
    api_key: str,
) -> None:
    """Write ``LLM_PROVIDER_<N>`` label + ``LLM_PROVIDER_<N>_API_KEY`` to ``.env``."""
    env_path = tmp_path / ".env"
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    lines.append(f"LLM_PROVIDER_{env_index}={label}")
    lines.append(f"LLM_PROVIDER_{env_index}_API_KEY={api_key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bootstrap_opencode_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    label: str,
    url: str,
    model_id: str,
    harness: str = "opencode",
    env_index: int = 1,
    api_key: str = "registry-test-key",
) -> str:
    """Register one provider via config registry + indexed secret (no presets)."""
    cfg_path = tmp_path / ".mergecraft" / "config.yaml"
    if not cfg_path.is_file():
        scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    for key in LEGACY_GATEWAY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    write_registry_provider_row(
        tmp_path,
        label=label,
        harness=harness,
        env_index=env_index,
        url=url,
        models=[{"id": model_id, "modelIndex": 1}],
    )
    write_indexed_provider_secret(
        tmp_path,
        env_index=env_index,
        label=label,
        api_key=api_key,
    )
    monkeypatch.setenv(f"LLM_PROVIDER_{env_index}", label)
    monkeypatch.setenv(f"LLM_PROVIDER_{env_index}_API_KEY", api_key)
    return format_model_slug(label, model_id)


def bootstrap_nous_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str = NOUS_BASE_URL,
    model_id: str = NOUS_TENCENT_HY3,
    api_key: str = "registry-nous-test-key",
) -> str:
    """Register Nous purely via config registry + indexed secret (no presets)."""
    return bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="nous",
        url=url,
        model_id=model_id,
        api_key=api_key,
    )


# BF #483 — ``provider migrate`` / config-secret split (D2, D7, D10).

BF_XFAIL = pytest.mark.xfail(reason="green after BF impl", strict=False)

LEGACY_API_KEY_MIGRATIONS: dict[str, tuple[str, str]] = {
    "OPENAI_API_KEY": ("openai", "API_KEY"),
    "ANTHROPIC_API_KEY": ("anthropic", "API_KEY"),
    "GEMINI_API_KEY": ("google", "API_KEY"),
    "CURSOR_API_KEY": ("cursor", "API_KEY"),
    "DEEPSEEK_API_KEY": ("deepseek", "API_KEY"),
    "NOUS_API_KEY": ("nous", "API_KEY"),
}

LEGACY_STRUCTURE_IN_ENV: tuple[str, ...] = (
    "harness",
    "envIndex",
    "modelChain",
    "authKind",
)

BEDROCK_LEGACY_SECRET_KEYS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

BEDROCK_LEGACY_CONFIG_KEYS: tuple[str, ...] = (
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
)

VERTEX_LEGACY_SECRET_KEYS: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)

VERTEX_LEGACY_CONFIG_KEYS: tuple[str, ...] = (
    "GOOGLE_CLOUD_PROJECT",
    "VERTEX_LOCATION",
)

CREDENTIAL_SUBSTRINGS_IN_CONFIG: tuple[str, ...] = (
    "api_key",
    "apiKey",
    "secret",
    "password",
    "token",
)


def write_env_pairs(tmp_path: Path, pairs: Mapping[str, str]) -> None:
    """Append ``KEY=value`` lines to ``tmp_path/.env``."""
    env_path = tmp_path / ".env"
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    for key, value in pairs.items():
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def stub_mergecraft_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point ``MERGECRAFT_ENV`` at ``tmp_path/.env``."""
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))


def assert_output_never_contains_secret(output: str, secret: str) -> None:
    """Fail when *output* leaks a credential value (BF migrate diff contract)."""
    assert secret not in output, f"migrate output must not contain secret value {secret!r}"


def require_provider_migrate_symbols() -> Any:
    """Import ``provider_cmd`` and require BF migrate helpers to exist."""
    module = import_provider_cmd()
    for name in (
        "migrate_cmd",
        "plan_provider_migration",
        "apply_provider_migration",
        "migration_secret_fingerprint",
        "validate_config_secret_split",
        "resolve_indexed_credential",
    ):
        if not hasattr(module, name):
            pytest.fail(f"{PROVIDER_CMD_MODULE}.{name} is not implemented")
    return module


def config_text(tmp_path: Path) -> str:
    """Return raw ``.mergecraft/config.yaml`` text."""
    path = tmp_path / ".mergecraft" / "config.yaml"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def env_text(tmp_path: Path) -> str:
    """Return raw ``.env`` text."""
    path = tmp_path / ".env"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# BG #484 — ``workflow`` CLI authoring + surgical workflow YAML mutator (D9).

BG_XFAIL = pytest.mark.xfail(reason="green after BG impl", strict=False)

WORKFLOW_CMD_MODULE = "mergecraft.cli.workflow_cmd"
WORKFLOW_WF_YAML_MODULE = "mergecraft.cli.workflow_wf_yaml"

WORKFLOW_DEFAULT_RELATIVE_PATH = ".github/workflows/mergecraft.yml"

# Owned keys the workflow mutator may insert/replace inside mergeCraft steps.
WORKFLOW_OWNED_WITH_KEYS: tuple[str, ...] = ("model",)

WORKFLOW_OWNED_ENV_PREFIXES: tuple[str, ...] = (
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_",
    "LLM_PROVIDER_",
)

WORKFLOW_ONE_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    name: mergecraft review
    runs-on: ubuntu-latest
    # === PRESERVE: header comment block (#486) ===
    timeout-minutes: 65
    steps:
      - name: mergeCraft PR review
        id: mergecraft_nous
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: openai/gpt-codex
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
"""

WORKFLOW_TWO_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    name: mergecraft review
    runs-on: ubuntu-latest
    timeout-minutes: 65
    steps:
      - name: mergeCraft PR review (Nous primary)
        id: mergecraft_nous
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: nous/tencent/hy3
        env:
          MERGECRAFT_CUSTOM_PROVIDER_BASE_URL: https://inference-api.nousresearch.com/v1
          MERGECRAFT_CUSTOM_PROVIDER_API_KEY: ${{ secrets.NOUS_API_KEY }}

      - name: mergeCraft PR review (Codex fallback)
        id: mergecraft_codex
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: openai/gpt-codex
        env:
          CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
"""


def import_workflow_cmd() -> Any:
    """Import ``mergecraft.cli.workflow_cmd`` or fail with a clear message."""
    try:
        return importlib.import_module(WORKFLOW_CMD_MODULE)
    except ImportError as exc:
        pytest.fail(f"{WORKFLOW_CMD_MODULE} is not implemented yet: {exc}")


def import_workflow_wf_yaml() -> Any:
    """Import ``mergecraft.cli.workflow_wf_yaml`` or fail with a clear message."""
    try:
        return importlib.import_module(WORKFLOW_WF_YAML_MODULE)
    except ImportError as exc:
        pytest.fail(f"{WORKFLOW_WF_YAML_MODULE} is not implemented yet: {exc}")


def require_workflow_cmd_symbols() -> Any:
    """Import workflow CLI and require BG subcommands/helpers."""
    module = import_workflow_cmd()
    for name in (
        "app",
        "list_cmd",
        "provider_add_cmd",
        "provider_harnesses_cmd",
        "model_add_cmd",
        "model_prioritize_cmd",
        "agents_setmodel_cmd",
    ):
        if not hasattr(module, name):
            pytest.fail(f"{WORKFLOW_CMD_MODULE}.{name} is not implemented")
    return module


def require_workflow_wf_yaml_symbols() -> Any:
    """Import workflow YAML mutator and require BG owned-key helpers."""
    module = import_workflow_wf_yaml()
    for name in (
        "WORKFLOW_OWNED_WITH_KEYS",
        "WORKFLOW_OWNED_ENV_PREFIXES",
        "WorkflowYamlError",
        "WorkflowChange",
        "apply_provider_env_wiring",
        "apply_model_wiring",
        "render_workflow_diff",
    ):
        if not hasattr(module, name):
            pytest.fail(f"{WORKFLOW_WF_YAML_MODULE}.{name} is not implemented")
    return module


def scaffold_workflow_file(
    tmp_path: Path,
    body: str,
    *,
    relative_path: str = WORKFLOW_DEFAULT_RELATIVE_PATH,
) -> Path:
    """Write a consumer workflow YAML under *tmp_path*."""
    workflow_path = tmp_path / relative_path
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(body, encoding="utf-8")
    return workflow_path


def workflow_text(tmp_path: Path, *, relative_path: str = WORKFLOW_DEFAULT_RELATIVE_PATH) -> str:
    """Return raw workflow YAML text."""
    path = tmp_path / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def indexed_custom_provider_base_url(env_index: int) -> str:
    """Return ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_<N>`` for workflow env blocks."""
    return f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{env_index}"


def indexed_custom_provider_api_key(env_index: int) -> str:
    """Return ``LLM_PROVIDER_<N>_API_KEY`` for workflow env blocks."""
    return f"LLM_PROVIDER_{env_index}_API_KEY"


def _line_is_owned_workflow_mutation(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    for key in WORKFLOW_OWNED_WITH_KEYS:
        if stripped.startswith(f"{key}:"):
            return True
    for prefix in WORKFLOW_OWNED_ENV_PREFIXES:
        if stripped.split(":", 1)[0].strip().startswith(prefix):
            return True
    return False


def assert_only_owned_workflow_keys_changed(before: str, after: str) -> None:
    """Assert byte-stable surgery: only owned ``with:``/``env:`` keys may differ."""

    def non_owned_lines(text: str) -> list[str]:
        return [line for line in text.splitlines() if not _line_is_owned_workflow_mutation(line)]

    assert non_owned_lines(before) == non_owned_lines(after)
