from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mem0_server.auth import AuthError, ForbiddenError, claim_at

from .conftest import ISSUER


def test_valid_token(verifier, make_token):
    principal = verifier.verify(make_token(sub="u-1", preferred_username="alice"))
    assert principal.user_id == "u-1"
    assert principal.username == "alice"


def test_any_configured_audience_is_accepted(verifier, make_token):
    assert verifier.verify(make_token(aud=["something-else", "other-client"])).user_id == "alice"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"aud": "not-us"},
        {"iss": "https://evil.example.com"},
        {"exp_in": -3600},
        {"kid": "unknown"},
    ],
)
def test_rejected_tokens(verifier, make_token, kwargs):
    with pytest.raises(AuthError):
        verifier.verify(make_token(**kwargs))


def test_foreign_signature_rejected(verifier):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": "mem0", "iat": 0, "exp": 2**31}, other, "RS256", headers={"kid": "k1"}
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_hs256_rejected(verifier):
    token = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": "mem0", "iat": 0, "exp": 2**31},
        "secret-that-is-long-enough-for-hs256-xxxx",
        "HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_missing_role_forbidden(verifier, make_token):
    with pytest.raises(ForbiddenError):
        verifier.verify(make_token(roles=("default-roles-cloud",)))


def test_missing_user_claim(verifier, make_token):
    with pytest.raises(AuthError):
        verifier.verify(make_token(sub=""))


def test_claim_at():
    claims = {"realm_access": {"roles": ["a"]}, "roles": ["b"]}
    assert claim_at(claims, "realm_access.roles") == ["a"]
    assert claim_at(claims, "roles") == ["b"]
    assert claim_at(claims, "missing.path") is None
