"""Typed environment settings: one reader for env, ``.env`` and later config.

``mergecraft.config.env`` is the leaf every setting model lives in. It imports
only ``pydantic``, ``pydantic_settings``, ``python-dotenv`` and itself, so it
never joins the cycle ``mergecraft.config.settings`` works around and one
import here can never drag a resolver in with it.

This package owns:
    * the shared building blocks — :data:`EnvBool`, :class:`ExactFlag`,
      :class:`EnvSettingsError`, :func:`from_env` and the startup registry;
    * the one ``.env`` reader — :class:`LocalDotEnv` over ``python-dotenv``.
"""

from __future__ import annotations

from mergecraft.config.env._base import (
    ENV_SETTINGS_CONFIG,
    EnvBool,
    EnvSettings,
    EnvSettingsError,
    ExactFlag,
    fail_closed_env_bool,
    from_env,
    register_env_model,
    registered_env_models,
    validate_env_settings,
)
from mergecraft.config.env.dotenv import (
    DotEnvFileSource,
    LocalDotEnv,
    local_dotenv_values,
)
from mergecraft.config.env.tracing import TracingEnv

__all__ = [
    "ENV_SETTINGS_CONFIG",
    "DotEnvFileSource",
    "EnvBool",
    "EnvSettings",
    "EnvSettingsError",
    "ExactFlag",
    "LocalDotEnv",
    "TracingEnv",
    "fail_closed_env_bool",
    "from_env",
    "local_dotenv_values",
    "register_env_model",
    "registered_env_models",
    "validate_env_settings",
]
