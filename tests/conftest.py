from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from mem0_server.app import create_app
from mem0_server.auth import TokenVerifier
from mem0_server.config import Settings

ISSUER = "https://id.example.com/realms/test"
AUDIENCE = "mem0"


class StaticJWKClient:
    """Stands in for jwt.PyJWKClient: one known key, no network."""

    def __init__(self, public_key: Any):
        self._key = jwt.PyJWK.from_dict(
            {**jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True), "kid": "k1", "alg": "RS256"}
        )

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if jwt.get_unverified_header(token).get("kid") != "k1":
            raise jwt.PyJWKClientError("unknown kid")
        return self._key


class FakeMemory:
    """Enough of mem0.Memory to exercise the API's scoping."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []

    @staticmethod
    def _matches(item: dict[str, Any], filters: dict[str, Any]) -> bool:
        return all(item.get(k) == v for k, v in filters.items() if k in ("user_id", "agent_id", "run_id"))

    def add(self, messages, *, user_id=None, agent_id=None, run_id=None, metadata=None, infer=True):
        self.calls.append(("add", {"user_id": user_id, "agent_id": agent_id, "run_id": run_id, "infer": infer}))
        text = messages if isinstance(messages, str) else " ".join(m["content"] for m in messages)
        mid = str(uuid.uuid4())
        item = {"id": mid, "memory": text, "user_id": user_id}
        if agent_id:
            item["agent_id"] = agent_id
        if run_id:
            item["run_id"] = run_id
        if metadata:
            item["metadata"] = metadata
        self.items[mid] = item
        return {"results": [{"id": mid, "memory": text, "event": "ADD"}]}

    def get(self, memory_id):
        return self.items.get(memory_id)

    def get_all(self, *, filters, top_k=20):
        self.calls.append(("get_all", filters))
        return {"results": [i for i in self.items.values() if self._matches(i, filters)][:top_k]}

    def search(self, query, *, filters, top_k=20, **kwargs):
        self.calls.append(("search", filters))
        hits = [i for i in self.items.values() if self._matches(i, filters) and query in i["memory"]]
        return {"results": hits[:top_k]}

    def update(self, memory_id, text=None, metadata=None):
        self.items[memory_id]["memory"] = text
        return {"message": "Memory updated successfully!"}

    def history(self, memory_id):
        return [{"memory_id": memory_id, "event": "ADD"}]

    def delete(self, memory_id):
        del self.items[memory_id]

    def delete_all(self, user_id=None, agent_id=None, run_id=None):
        self.calls.append(("delete_all", {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}))
        scope = {k: v for k, v in {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}.items() if v}
        for mid in [m for m, i in self.items.items() if self._matches(i, scope)]:
            del self.items[mid]


@pytest.fixture(scope="session")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        oidc_issuer=ISSUER,
        oidc_audiences=(AUDIENCE, "other-client"),
        required_roles=("llm-user",),
        llm_base_url="http://llm",
        llm_model="m",
        embedder_base_url="http://emb",
        embedder_model="e",
        pg_connection_string="postgresql://x",
    )


@pytest.fixture
def make_token(private_key):
    def _make(sub="alice", roles=("llm-user",), aud=AUDIENCE, iss=ISSUER, exp_in=300, kid="k1", **extra):
        now = int(time.time())
        claims = {"sub": sub, "iss": iss, "aud": aud, "iat": now, "exp": now + exp_in, "roles": list(roles), **extra}
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})

    return _make


@pytest.fixture
def verifier(settings, private_key) -> TokenVerifier:
    return TokenVerifier(settings, jwks_client=StaticJWKClient(private_key.public_key()))


@pytest.fixture
def fake_memory() -> FakeMemory:
    return FakeMemory()


@pytest.fixture
def client(settings, verifier, fake_memory) -> TestClient:
    return TestClient(create_app(settings, memory_factory=lambda: fake_memory, verifier=verifier))


@pytest.fixture
def auth(make_token):
    def _auth(sub="alice", **kwargs) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(sub=sub, **kwargs)}"}

    return _auth
