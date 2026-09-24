"""OIDC access-token verification.

The token is verified here even when a gateway in front has already checked
it: the user_id every memory is filed under comes from this token, so the
service must not trust anything it has not verified itself.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import jwt

from .config import Settings

logger = logging.getLogger(__name__)

# Asymmetric algorithms only. HS* would let anyone holding the (public) JWKS
# forge tokens if a key were ever misread as a shared secret.
ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]


class AuthError(Exception):
    """The request is not authenticated (401)."""


class ForbiddenError(Exception):
    """The token is valid but lacks a required role (403)."""


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


def claim_at(claims: dict[str, Any], path: str) -> Any:
    """Look up a dotted claim path such as `realm_access.roles`."""
    value: Any = claims
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class TokenVerifier:
    def __init__(self, settings: Settings, jwks_client: jwt.PyJWKClient | None = None):
        self._settings = settings
        self._jwks_client = jwks_client
        self._lock = threading.Lock()

    def _client(self) -> jwt.PyJWKClient:
        if self._jwks_client is None:
            with self._lock:
                if self._jwks_client is None:
                    url = self._settings.oidc_jwks_url or self._discover_jwks_url()
                    # Keys are cached; an unknown `kid` (key rotation) triggers
                    # one refetch before the token is rejected.
                    self._jwks_client = jwt.PyJWKClient(url, cache_keys=True, lifespan=600, timeout=10)
        return self._jwks_client

    def _discover_jwks_url(self) -> str:
        url = f"{self._settings.oidc_issuer}/.well-known/openid-configuration"
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 -- configured https issuer
            doc = json.load(resp)
        if doc.get("issuer", "").rstrip("/") != self._settings.oidc_issuer:
            raise RuntimeError(f"discovery document at {url} names a different issuer: {doc.get('issuer')!r}")
        return doc["jwks_uri"]

    def verify(self, token: str) -> Principal:
        s = self._settings
        try:
            signing_key = self._client().get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=list(s.oidc_audiences),
                issuer=s.oidc_issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWKClientConnectionError as exc:
            # The IdP being unreachable is not the caller's fault, but there is
            # still no way to tell a good token from a forged one.
            logger.warning("JWKS fetch failed: %s", exc)
            raise AuthError("cannot verify token right now") from exc
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {exc}") from exc

        user_id = claims.get(s.user_id_claim)
        if not isinstance(user_id, str) or not user_id:
            raise AuthError(f"token has no {s.user_id_claim!r} claim")

        if s.required_roles:
            roles = claim_at(claims, s.roles_claim)
            if isinstance(roles, str):
                roles = [roles]
            if not isinstance(roles, list) or not set(s.required_roles).intersection(roles):
                raise ForbiddenError("missing required role")

        return Principal(user_id=user_id, username=claims.get("preferred_username"), claims=claims)
