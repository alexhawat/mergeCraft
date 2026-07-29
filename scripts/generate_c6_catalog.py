#!/usr/bin/env python3
"""One-shot generator for C6 P1-P3 manifests and parser fixtures."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/mergecraft/analyzers/catalog"
FIXTURES = ROOT / "tests/analyzers/fixtures"

PLACEHOLDER_SHA = "0000000000000000000000000000000000000000000000000000000000000000"

SARIF_TEMPLATE = {
    "version": "2.1.0",
    "runs": [
        {
            "tool": {"driver": {"name": "TOOL", "rules": [{"id": "RULE1"}]}},
            "results": [
                {
                    "ruleId": "RULE1",
                    "level": "warning",
                    "message": {"text": "minimal fixture finding"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "src/example.ext"},
                                "region": {"startLine": 1, "endLine": 1},
                            }
                        }
                    ],
                }
            ],
        }
    ],
}

NATIVE_TEMPLATES: dict[str, object] = {
    "ruff_json": [
        {
            "filename": "src/example.py",
            "location": {"row": 1, "column": 1},
            "message": "minimal",
            "code": "F401",
            "severity": "warning",
        }
    ],
    "shellcheck_json": [
        {
            "file": "scripts/example.sh",
            "line": 1,
            "column": 1,
            "level": "warning",
            "code": 2086,
            "message": "minimal",
        }
    ],
    "eslint_json": [
        {
            "filePath": "src/index.js",
            "messages": [
                {
                    "ruleId": "no-unused-vars",
                    "severity": 1,
                    "message": "minimal",
                    "line": 1,
                    "column": 1,
                }
            ],
        }
    ],
    "mypy_json": '{"file": "src/example.py", "line": 1, "column": 1, "message": "minimal", "severity": "error"}\n',
    "pyright_json": {
        "generalDiagnostics": [
            {
                "file": "src/example.py",
                "severity": "error",
                "message": "minimal",
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
            }
        ]
    },
    "oasdiff_json": {"breakingChanges": [{"id": "response-property-removed", "level": "breaking"}]},
    "osv_json": {
        "results": [
            {
                "source": {"path": "requirements.txt", "type": "lockfile"},
                "packages": [
                    {
                        "package": {"name": "example", "ecosystem": "PyPI", "version": "1.0.0"},
                        "vulnerabilities": [
                            {
                                "id": "CVE-2024-0001",
                                "severity": [{"type": "CVSS_V3", "score": "7.5 HIGH"}],
                            }
                        ],
                    }
                ],
            }
        ]
    },
    "squawk_json": [{"name": "require-timeout-settings", "level": "Warning"}],
    "trivy_json": {
        "Results": [
            {
                "Target": "requirements.txt",
                "Vulnerabilities": [
                    {"VulnerabilityID": "CVE-2024-0001", "Severity": "HIGH", "Title": "minimal"}
                ],
            }
        ]
    },
    "trufflehog_jsonl": '{"SourceMetadata":{"Data":{"Filesystem":{"file":"config/.env","line":1}}},"DetectorName":"AWS","Verified":false}\n',
}

NEW_MANIFESTS: list[dict[str, object]] = [
    # P1
    {
        "id": "golangci-lint",
        "category": "lint",
        "languages": ["go"],
        "detect": {"files": ["*.go"]},
        "command": ["golangci-lint", "run", "--out-format", "sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.62.2",
        "runtime": "managed",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/golangci/golangci-lint/releases/download/v1.62.2/golangci-lint-1.62.2-linux-amd64.tar.gz",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": "go-lint",
    },
    {
        "id": "clippy",
        "category": "lint",
        "languages": ["rust"],
        "detect": {"files": ["*.rs", "Cargo.toml"]},
        "command": ["cargo", "clippy", "--message-format=json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.83.0",
        "runtime": "repo-native",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": "rust-lint",
    },
    {
        "id": "tflint",
        "category": "lint",
        "languages": ["terraform"],
        "detect": {"files": ["*.tf", "*.tfvars"]},
        "command": ["tflint", "--format", "sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.54.0",
        "runtime": "managed",
        "timeout_s": 180,
        "trust": "untrusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/terraform-linters/tflint/releases/download/v0.54.0/tflint_linux_amd64.zip",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": "iac-scanner",
    },
    {
        "id": "checkov",
        "category": "security",
        "languages": ["terraform", "cloudformation"],
        "detect": {"files": ["*.tf", "*.yaml", "*.yml", "serverless.yml"]},
        "command": ["checkov", "-f", "{files}", "-o", "sarif"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "3.2.366",
        "runtime": "managed",
        "timeout_s": 300,
        "trust": "untrusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://pypi.org/project/checkov/3.2.366/",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": "iac-scanner",
    },
    {
        "id": "sqlfluff",
        "category": "lint",
        "languages": ["sql"],
        "detect": {"files": ["*.sql", ".sqlfluff", "pyproject.toml"]},
        "command": ["sqlfluff", "lint", "--format", "json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "3.3.0",
        "runtime": "managed",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://pypi.org/project/sqlfluff/3.3.0/",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "presidio",
        "category": "security",
        "languages": [],
        "detect": {"files": ["*.txt", "*.md", "*.yaml", "*.json"]},
        "command": ["presidio-analyzer", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "2.2.355",
        "runtime": "container",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://hub.docker.com/r/mcr.microsoft.com/presidio-analyzer",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    # P2
    {
        "id": "flake8",
        "category": "lint",
        "languages": ["python"],
        "detect": {"files": ["*.py", ".flake8", "setup.cfg", "pyproject.toml"]},
        "command": ["flake8", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "7.1.1",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": "python-lint",
    },
    {
        "id": "cppcheck",
        "category": "lint",
        "languages": ["c", "cpp"],
        "detect": {"files": ["*.c", "*.cpp", "*.h", "*.hpp"]},
        "command": ["cppcheck", "--output-format=sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "2.16.0",
        "runtime": "managed",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/danmar/cppcheck/releases/download/2.16.0/cppcheck-2.16.0-x64-Linux.tgz",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "detekt",
        "category": "lint",
        "languages": ["kotlin"],
        "detect": {"files": ["*.kt", "*.kts", "detekt.yml"]},
        "command": ["detekt", "--input", "{files}", "--report", "sarif:detekt.sarif"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.23.7",
        "runtime": "repo-native",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "rubocop",
        "category": "lint",
        "languages": ["ruby"],
        "detect": {"files": ["*.rb", ".rubocop.yml"]},
        "command": ["rubocop", "--format", "sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.69.2",
        "runtime": "repo-native",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": "ruby-lint",
    },
    {
        "id": "brakeman",
        "category": "security",
        "languages": ["ruby"],
        "detect": {"files": ["*.rb", "Gemfile", "config/routes.rb"]},
        "command": ["brakeman", "-f", "sarif", "-o", "brakeman.sarif"],
        "scope": "repo",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "6.4.0",
        "runtime": "repo-native",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "phpstan",
        "category": "lint",
        "languages": ["php"],
        "detect": {"files": ["*.php", "phpstan.neon", "phpstan.neon.dist"]},
        "command": ["phpstan", "analyse", "--error-format=json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "2.1.2",
        "runtime": "repo-native",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "stylelint",
        "category": "lint",
        "languages": ["css"],
        "detect": {"files": ["*.css", "*.scss", "stylelint.config.js", ".stylelintrc.json"]},
        "command": ["stylelint", "--formatter", "json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "16.12.0",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "prisma-lint",
        "category": "lint",
        "languages": ["prisma"],
        "detect": {"files": ["*.prisma"]},
        "command": ["prisma-lint", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.10.1",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "regal",
        "category": "lint",
        "languages": ["rego"],
        "detect": {"files": ["*.rego"]},
        "command": ["regal", "lint", "--format", "sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.27.0",
        "runtime": "managed",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/StyraInc/regal/releases/download/v0.27.0/regal_Linux_x86_64.tar.gz",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "yamllint",
        "category": "lint",
        "languages": ["yaml"],
        "detect": {"files": ["*.yaml", "*.yml", ".yamllint"]},
        "command": ["yamllint", "-f", "sarif", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.35.1",
        "runtime": "managed",
        "timeout_s": 120,
        "trust": "untrusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://pypi.org/project/yamllint/1.35.1/",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "dotenv-linter",
        "category": "lint",
        "languages": [],
        "detect": {"files": [".env*", "*.env"]},
        "command": ["dotenv-linter", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "3.3.0",
        "runtime": "managed",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/dotenv-linter/dotenv-linter/releases/download/v3.3.0/dotenv-linter-v3.3.0-x86_64-unknown-linux-gnu.tar.gz",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "circleci",
        "category": "lint",
        "languages": ["yaml"],
        "detect": {"files": [".circleci/config.yml"]},
        "command": ["circleci", "config", "validate", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.1.31438",
        "runtime": "managed",
        "timeout_s": 120,
        "trust": "untrusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://circleci.com/docs/local-cli/",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    # P3
    {
        "id": "checkmake",
        "category": "lint",
        "languages": ["make"],
        "detect": {"files": ["Makefile", "makefile", "*.mk"]},
        "command": ["checkmake", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.2.2",
        "runtime": "managed",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/mrtazz/checkmake/releases/download/0.2.2/checkmake-0.2.2.linux.amd64",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "ember-template-lint",
        "category": "lint",
        "languages": ["ember"],
        "detect": {"files": ["*.hbs", ".template-lintrc.js"]},
        "command": ["ember-template-lint", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "6.0.0",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "htmlhint",
        "category": "lint",
        "languages": ["html"],
        "detect": {"files": ["*.html", ".htmlhintrc"]},
        "command": ["htmlhint", "--format", "json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.1.4",
        "runtime": "repo-native",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "languagetool",
        "category": "lint",
        "languages": ["text"],
        "detect": {"files": ["*.md", "*.txt"]},
        "command": ["languagetool", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "6.5",
        "runtime": "container",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://hub.docker.com/r/erigones/languagetool",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "manifest-only — LanguageTool runtime not bundled on Linux runners (C6 out of scope)",
    },
    {
        "id": "luacheck",
        "category": "lint",
        "languages": ["lua"],
        "detect": {"files": ["*.lua", ".luacheckrc"]},
        "command": ["luacheck", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.2.0",
        "runtime": "repo-native",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "markdownlint",
        "category": "lint",
        "languages": ["markdown"],
        "detect": {"files": ["*.md", ".markdownlint.json", ".markdownlint.yaml"]},
        "command": ["markdownlint", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.37.4",
        "runtime": "repo-native",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "phpmd",
        "category": "lint",
        "languages": ["php"],
        "detect": {"files": ["*.php"]},
        "command": ["phpmd", "{files}", "sarif", "cleancode,codesize,design,naming,unusedcode"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "2.15.0",
        "runtime": "repo-native",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "phpcs",
        "category": "lint",
        "languages": ["php"],
        "detect": {"files": ["*.php", "phpcs.xml", "phpcs.xml.dist"]},
        "command": ["phpcs", "--report=json", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "3.11.2",
        "runtime": "repo-native",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": "php-lint",
    },
    {
        "id": "pmd",
        "category": "lint",
        "languages": ["java"],
        "detect": {"files": ["*.java", "pmd.ruleset.xml"]},
        "command": ["pmd", "check", "-f", "sarif", "-d", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "7.9.0",
        "runtime": "managed",
        "timeout_s": 300,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.9.0/pmd-dist-7.9.0-bin.zip",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
    },
    {
        "id": "shopify-theme-check",
        "category": "lint",
        "languages": ["liquid"],
        "detect": {"files": ["*.liquid", ".theme-check.yml"]},
        "command": ["theme-check", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.15.0",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "manifest-only — Shopify Theme Check not bundled on Linux runners (C6 out of scope)",
    },
    {
        "id": "smarty-lint",
        "category": "lint",
        "languages": ["smarty"],
        "detect": {"files": ["*.tpl", ".smarty-lint.json"]},
        "command": ["smarty-lint", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.0.0",
        "runtime": "repo-native",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {},
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "manifest-only — Smarty Lint not bundled on Linux runners (C6 out of scope)",
    },
    {
        "id": "fortitude",
        "category": "lint",
        "languages": ["fortran"],
        "detect": {"files": ["*.f90", "*.f95", ".fortitude.toml"]},
        "command": ["fortitude", "check", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.6.2",
        "runtime": "managed",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://pypi.org/project/fortitude/0.6.2/",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "manifest-only — Fortitude not bundled on Linux runners (C6 out of scope)",
    },
    # Declared-not-runnable
    {
        "id": "clang-tidy",
        "category": "lint",
        "languages": ["c", "cpp"],
        "detect": {"files": ["compile_commands.json", "*.cpp", "*.cc"]},
        "command": ["clang-tidy", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "19.1.0",
        "runtime": "container",
        "timeout_s": 600,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {"url": "https://hub.docker.com/_/clang", "sha256": PLACEHOLDER_SHA}
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "requires compile_commands.json — mergeCraft never guesses compiler flags (C4)",
    },
    {
        "id": "infer",
        "category": "security",
        "languages": ["java", "c", "cpp"],
        "detect": {"files": ["compile_commands.json", "pom.xml", "build.gradle"]},
        "command": ["infer", "run", "--", "make"],
        "scope": "repo",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.1.0",
        "runtime": "container",
        "timeout_s": 900,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://github.com/facebook/infer/releases/tag/v1.1.0",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "requires compilation database and build — container-only heavyweight (C4)",
    },
    {
        "id": "psscriptanalyzer",
        "category": "lint",
        "languages": ["powershell"],
        "detect": {"files": ["*.ps1", "*.psm1"]},
        "command": ["Invoke-ScriptAnalyzer", "-Path", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.23.0",
        "runtime": "managed",
        "timeout_s": 120,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {
                "url": "https://www.powershellgallery.com/packages/PSScriptAnalyzer",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "requires non-Linux runner — Windows/macOS only (C6 out of scope)",
    },
    {
        "id": "blinter",
        "category": "lint",
        "languages": ["batch"],
        "detect": {"files": ["*.bat", "*.cmd"]},
        "command": ["blinter", "{files}"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "1.0.0",
        "runtime": "managed",
        "timeout_s": 60,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "linux-amd64": {"url": "https://example.com/blinter", "sha256": PLACEHOLDER_SHA}
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "requires non-Linux runner — Windows batch lint not supported on Linux (C6)",
    },
    {
        "id": "swiftlint",
        "category": "lint",
        "languages": ["swift"],
        "detect": {"files": ["*.swift", ".swiftlint.yml"]},
        "command": ["swiftlint", "lint", "--reporter", "sarif"],
        "scope": "diff",
        "parser": "sarif",
        "supports_fix": False,
        "default_enabled": False,
        "version": "0.57.0",
        "runtime": "managed",
        "timeout_s": 180,
        "trust": "trusted",
        "severity_map": {"error": "Major", "warning": "Minor", "note": "Trivial"},
        "provenance": {
            "darwin-arm64": {
                "url": "https://github.com/realm/SwiftLint/releases/download/0.57.0/portable_swiftlint.zip",
                "sha256": PLACEHOLDER_SHA,
            }
        },
        "network_allowlist": [],
        "exclusive_group": None,
        "declared_unavailable": "requires non-Linux runner — SwiftLint needs macOS (C6 out of scope)",
    },
]

EXISTING_FIXTURE_SPECS: dict[str, str] = {
    "actionlint": "sarif",
    "hadolint": "sarif",
    "zizmor": "sarif",
    "shellcheck": "shellcheck_json",
    "ruff": "ruff_json",
    "eslint": "eslint_json",
    "mypy": "mypy_json",
    "pyright": "pyright_json",
    "basedpyright": "pyright_json",
    "oasdiff": "oasdiff_json",
    "osv-scanner": "osv_json",
    "squawk": "squawk_json",
    "trivy": "trivy_json",
    "trufflehog": "trufflehog_jsonl",
    "semgrep": "sarif",
    "ast-grep": "sarif",
    "opengrep": "sarif",
    "biome": "sarif",
    "oxlint": "sarif",
    "buf": "sarif",
    "pylint": "sarif",
    "agentsec": "agentsec",
}


def dump_yaml(data: dict[str, object]) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def write_sarif(tool_id: str) -> None:
    payload = json.loads(json.dumps(SARIF_TEMPLATE))
    payload["runs"][0]["tool"]["driver"]["name"] = tool_id
    path = FIXTURES / "sarif" / f"{tool_id}-minimal.sarif.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_native(tool_id: str, parser: str) -> None:
    path = FIXTURES / "native" / f"{tool_id}-minimal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    template = NATIVE_TEMPLATES[parser]
    if isinstance(template, str):
        path = FIXTURES / "native" / f"{tool_id}-minimal.jsonl"
        path.write_text(template, encoding="utf-8")
        return
    path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    import yaml

    for spec in NEW_MANIFESTS:
        tool_id = str(spec["id"])
        path = CATALOG / f"{tool_id}.yaml"
        path.write_text(dump_yaml(spec), encoding="utf-8")
        write_sarif(tool_id)

    # pylint: default_enabled false (C6.5)
    pylint_path = CATALOG / "pylint.yaml"
    pylint = yaml.safe_load(pylint_path.read_text(encoding="utf-8"))
    pylint["default_enabled"] = False
    pylint_path.write_text(dump_yaml(pylint), encoding="utf-8")

    # fixtures for existing catalog entries
    for tool_id, parser in EXISTING_FIXTURE_SPECS.items():
        if parser == "sarif":
            target = FIXTURES / "sarif" / f"{tool_id}-minimal.sarif.json"
            if not target.is_file():
                write_sarif(tool_id)
        elif parser == "agentsec":
            agentsec_dir = FIXTURES / "agentsec"
            agentsec_dir.mkdir(parents=True, exist_ok=True)
            target = agentsec_dir / "agentsec-minimal.yaml"
            if not target.is_file():
                target.write_text(
                    "rule_id: mcp-exfil-instructions\n"
                    "severity: Critical\n"
                    "message: minimal agentsec fixture\n",
                    encoding="utf-8",
                )
        else:
            target = FIXTURES / "native" / f"{tool_id}-minimal.json"
            jsonl_target = FIXTURES / "native" / f"{tool_id}-minimal.jsonl"
            if not target.is_file() and not jsonl_target.is_file():
                write_native(tool_id, parser)

    print(f"wrote {len(NEW_MANIFESTS)} new manifests")


if __name__ == "__main__":
    main()
