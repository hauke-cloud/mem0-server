from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mem0_server.app import create_app
from mem0_server.config import Settings


def test_health_needs_no_token(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_requires_token(client):
    r = client.get("/memories")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


def test_invalid_token(client):
    assert client.get("/memories", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_missing_role_is_403(client, auth):
    assert client.get("/memories", headers=auth(roles=())).status_code == 403


def test_token_scheme_alias(client, make_token):
    assert client.get("/me", headers={"Authorization": f"Token {make_token()}"}).json()["user_id"] == "alice"


def test_add_is_filed_under_token_subject(client, auth, fake_memory):
    r = client.post("/memories", json={"messages": "likes tea", "agent_id": "opencode"}, headers=auth("alice"))
    assert r.status_code == 200, r.text
    assert fake_memory.calls[-1] == ("add", {"user_id": "alice", "agent_id": "opencode", "run_id": None, "infer": True})


def test_user_id_in_body_is_rejected(client, auth):
    r = client.post("/memories", json={"messages": "x", "user_id": "bob"}, headers=auth("alice"))
    assert r.status_code == 422


@pytest.mark.parametrize("metadata", [{"user_id": "bob"}, {"nested": {"user_id": "bob"}}, {"hash": "x"}])
def test_reserved_metadata_rejected(client, auth, metadata):
    r = client.post("/memories", json={"messages": "x", "metadata": metadata}, headers=auth("alice"))
    assert r.status_code == 400


def test_users_are_isolated(client, auth):
    client.post("/memories", json={"messages": "alice secret"}, headers=auth("alice"))
    client.post("/memories", json={"messages": "bob secret"}, headers=auth("bob"))

    alice = client.get("/memories", headers=auth("alice")).json()["results"]
    assert [m["memory"] for m in alice] == ["alice secret"]

    hits = client.post("/search", json={"query": "secret"}, headers=auth("bob")).json()["results"]
    assert [m["memory"] for m in hits] == ["bob secret"]


@pytest.mark.parametrize(
    "filters",
    [
        {"user_id": "bob"},
        {"OR": [{"user_id": "bob"}]},
        {"$or": [{"user_id": "bob"}]},
    ],
)
def test_search_filters_cannot_name_a_user(client, auth, filters):
    r = client.post("/search", json={"query": "x", "filters": filters}, headers=auth("alice"))
    assert r.status_code == 400


def test_search_filters_are_anded_with_identity(client, auth, fake_memory):
    client.post("/search", json={"query": "x", "filters": {"project": "infra"}}, headers=auth("alice"))
    assert fake_memory.calls[-1] == ("search", {"project": "infra", "user_id": "alice"})


def test_foreign_memory_is_404_everywhere(client, auth):
    mid = client.post("/memories", json={"messages": "bob secret"}, headers=auth("bob")).json()["results"][0]["id"]
    alice = auth("alice")
    assert client.get(f"/memories/{mid}", headers=alice).status_code == 404
    assert client.get(f"/memories/{mid}/history", headers=alice).status_code == 404
    assert client.put(f"/memories/{mid}", json={"text": "pwned"}, headers=alice).status_code == 404
    assert client.delete(f"/memories/{mid}", headers=alice).status_code == 404
    assert client.get(f"/memories/{mid}", headers=auth("bob")).json()["memory"] == "bob secret"


def test_own_memory_crud(client, auth):
    h = auth("alice")
    mid = client.post("/memories", json={"messages": "v1"}, headers=h).json()["results"][0]["id"]
    assert client.put(f"/memories/{mid}", json={"text": "v2"}, headers=h).status_code == 200
    assert client.get(f"/memories/{mid}", headers=h).json()["memory"] == "v2"
    assert client.get(f"/memories/{mid}/history", headers=h).status_code == 200
    assert client.delete(f"/memories/{mid}", headers=h).status_code == 200
    assert client.get(f"/memories/{mid}", headers=h).status_code == 404


def test_delete_all_only_touches_caller(client, auth, fake_memory):
    client.post("/memories", json={"messages": "a"}, headers=auth("alice"))
    client.post("/memories", json={"messages": "b"}, headers=auth("bob"))
    assert client.delete("/memories", headers=auth("alice")).status_code == 200
    assert fake_memory.calls[-1] == ("delete_all", {"user_id": "alice", "agent_id": None, "run_id": None})
    assert len(client.get("/memories", headers=auth("bob")).json()["results"]) == 1


def test_memory_init_failure_is_503(settings, verifier, auth):
    def broken():
        raise RuntimeError("db down")

    client = TestClient(create_app(settings, memory_factory=broken, verifier=verifier))
    assert client.get("/memories", headers=auth()).status_code == 503


def test_auth_disabled_uses_dev_user():
    settings = Settings(auth_disabled=True, dev_user_id="me")
    client = TestClient(create_app(settings, memory_factory=lambda: None))
    assert client.get("/me").json()["user_id"] == "me"


def test_mem0_config_shape(settings):
    config = settings.mem0_config()
    assert config["vector_store"]["config"]["embedding_model_dims"] == 1024
    assert "embedding_dims" not in config["embedder"]["config"]
    assert config["llm"]["config"]["openai_base_url"] == "http://llm"
