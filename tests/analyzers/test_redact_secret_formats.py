"""Token formats ``redact_secrets`` must match (W1.1-5).

Values are assembled at runtime so no credential-shaped literal sits in the tree.
"""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_secrets

_ALNUM = "aB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW1xY"


def _alnum(length: int) -> str:
    return (_ALNUM * (length // len(_ALNUM) + 1))[:length]


_FORMATS = {
    "npm-token": ("npm_" + _alnum(36), "npm_"),
    "slack-webhook": (
        "url https://hooks.slack.com/services/T" + "0" * 8 + "/B" + "0" * 8 + "/" + "X" * 24,
        "T00000000",
    ),
    "short-password-colon": ("password: " + "hunter2", "hunter2"),
    "short-password-equals": ("passwd=" + "s3cr3t", "s3cr3t"),
    "prefixed-password-key": ("DB_PASSWORD=" + "correcthorse", "correcthorse"),
    "prefixed-token-key": ("export GITHUB_TOKEN=" + "ghp_" + "shortbutreal1234", "shortbutreal"),
    "aws-secret-access-key": (
        "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/" + _alnum(18),
        "wJalrXUtnFEMI",
    ),
}


@pytest.mark.parametrize(("text", "leak"), list(_FORMATS.values()), ids=list(_FORMATS))
def test_secret_format_is_redacted(text: str, leak: str) -> None:
    assert leak not in redact_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "input_tokens=120",
        "max_tokens = 4096",
        "Enter password:\nnext line",
        "token_count: 12",
    ],
    ids=["usage-count", "max-tokens", "password-prompt-newline", "token-count"],
)
def test_non_credential_assignments_are_left_alone(text: str) -> None:
    assert redact_secrets(text) == text
