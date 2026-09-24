"""Settings, read once from the environment."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in _env(name).split(",") if v.strip())


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # --- OIDC -----------------------------------------------------------------
    # Every request must carry an access token from this issuer. The user the
    # token belongs to is the only user whose memories the request can touch.
    oidc_issuer: str = ""
    # Accepted `aud` values; a token must name at least one of them.
    oidc_audiences: tuple[str, ...] = ()
    # Empty: taken from <issuer>/.well-known/openid-configuration.
    oidc_jwks_url: str = ""
    # Claim that becomes the mem0 user_id. `sub` is stable across renames;
    # `preferred_username` is readable but changes when the user is renamed.
    user_id_claim: str = "sub"
    # Roles, any of which lets a token in. Empty: every valid token is let in.
    required_roles: tuple[str, ...] = ()
    # Dotted path to the roles array, e.g. `roles` or `realm_access.roles`.
    roles_claim: str = "roles"
    # Development only: no token at all, everything belongs to dev_user_id.
    auth_disabled: bool = False
    dev_user_id: str = "dev"

    # --- mem0 -----------------------------------------------------------------
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = "unused"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000
    embedder_base_url: str = ""
    embedder_model: str = ""
    embedder_api_key: str = "unused"
    embedding_dims: int = 1024
    # libpq connection string (URI or key=value), e.g.
    # postgresql://mem0@db:5432/mem0?sslmode=verify-full&sslcert=...
    pg_connection_string: str = ""
    collection_name: str = "memories"
    history_db_path: str = "/data/history.db"
    # Optional JSON file deep-merged over the generated mem0 config, for
    # anything the variables above do not cover (reranker, custom prompts, ...).
    mem0_config_file: str = ""

    # --- server ---------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            oidc_issuer=_env("OIDC_ISSUER").rstrip("/"),
            oidc_audiences=_env_list("OIDC_AUDIENCES"),
            oidc_jwks_url=_env("OIDC_JWKS_URL"),
            user_id_claim=_env("OIDC_USER_ID_CLAIM", "sub"),
            required_roles=_env_list("OIDC_REQUIRED_ROLES"),
            roles_claim=_env("OIDC_ROLES_CLAIM", "roles"),
            auth_disabled=_env_bool("AUTH_DISABLED"),
            dev_user_id=_env("DEV_USER_ID", "dev"),
            llm_base_url=_env("MEM0_LLM_BASE_URL"),
            llm_model=_env("MEM0_LLM_MODEL"),
            llm_api_key=_env("MEM0_LLM_API_KEY", "unused"),
            llm_temperature=_env_float("MEM0_LLM_TEMPERATURE", 0.1),
            llm_max_tokens=_env_int("MEM0_LLM_MAX_TOKENS", 2000),
            embedder_base_url=_env("MEM0_EMBEDDER_BASE_URL"),
            embedder_model=_env("MEM0_EMBEDDER_MODEL"),
            embedder_api_key=_env("MEM0_EMBEDDER_API_KEY", "unused"),
            embedding_dims=_env_int("MEM0_EMBEDDING_DIMS", 1024),
            pg_connection_string=_env("PG_CONNECTION_STRING"),
            collection_name=_env("MEM0_COLLECTION_NAME", "memories"),
            history_db_path=_env("MEM0_HISTORY_DB_PATH", "/data/history.db"),
            mem0_config_file=_env("MEM0_CONFIG_FILE"),
            host=_env("HOST", "0.0.0.0"),
            port=_env_int("PORT", 8000),
            log_level=_env("LOG_LEVEL", "info"),
        )

    def validate(self) -> None:
        missing = []
        if not self.auth_disabled:
            if not self.oidc_issuer:
                missing.append("OIDC_ISSUER")
            if not self.oidc_audiences:
                missing.append("OIDC_AUDIENCES")
        for name, value in (
            ("MEM0_LLM_BASE_URL", self.llm_base_url),
            ("MEM0_LLM_MODEL", self.llm_model),
            ("MEM0_EMBEDDER_BASE_URL", self.embedder_base_url),
            ("MEM0_EMBEDDER_MODEL", self.embedder_model),
            ("PG_CONNECTION_STRING", self.pg_connection_string),
        ):
            if not value:
                missing.append(name)
        if missing:
            raise ValueError(f"missing required settings: {', '.join(missing)}")

    def mem0_config(self) -> dict[str, Any]:
        """The dict handed to mem0's Memory.from_config."""
        config: dict[str, Any] = {
            "llm": {
                "provider": "openai",
                "config": {
                    "model": self.llm_model,
                    "api_key": self.llm_api_key,
                    "openai_base_url": self.llm_base_url,
                    "temperature": self.llm_temperature,
                    "max_tokens": self.llm_max_tokens,
                },
            },
            "embedder": {
                "provider": "openai",
                # embedding_dims deliberately left out: when set, mem0 sends it
                # as the OpenAI `dimensions` parameter, which OpenAI-compatible
                # servers without Matryoshka truncation reject. The vector
                # store below is told the size instead.
                "config": {
                    "model": self.embedder_model,
                    "api_key": self.embedder_api_key,
                    "openai_base_url": self.embedder_base_url,
                },
            },
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "connection_string": self.pg_connection_string,
                    "collection_name": self.collection_name,
                    "embedding_model_dims": self.embedding_dims,
                },
            },
            "history_db_path": self.history_db_path,
        }
        if self.mem0_config_file:
            with open(self.mem0_config_file, encoding="utf-8") as fh:
                config = deep_merge(config, json.load(fh))
        return config


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out
