# mem0-server

A small REST API over [mem0](https://github.com/mem0ai/mem0) that is **user aware through OIDC**:
every request carries an access token, the service verifies it against the issuer's JWKS,
and the token's subject is the mem0 `user_id`. A caller can never read, search, change or
delete another user's memories. This is what the stock mem0 server does not do: it
authenticates callers but still takes `user_id` from the request, and resolves memory ids for
anyone.

It is meant as the backend for an opencode memory plugin (or any other agent) running
against a self-hosted, OpenAI-compatible model server such as llama-swap.

## How it works

- **Identity**: `Authorization: Bearer <access token>` (`Token <...>`, which mem0's own
  clients send, is accepted too). Signature, `iss`, `aud`, `exp` are checked in-process; an
  optional role list gates access. The configured claim (`sub` by default) becomes `user_id`.
- **Scoping**: requests have no `user_id` parameter. Lists, searches and bulk deletes are
  filtered on the caller's `user_id`; anything addressed by id is loaded first and answers 404
  unless it belongs to the caller, so ids cannot be probed. Caller-supplied `metadata` and
  `filters` may not contain `user_id`, `agent_id`, `run_id` or mem0's bookkeeping keys.
- **Storage**: memories and embeddings in Postgres with pgvector; each memory's change history
  in mem0's SQLite file on a small volume (hence one replica).
- **Models**: one OpenAI-compatible chat model for fact extraction/merging, one embeddings
  model. Neither is contacted by the health probes.

## API

| Method | Path | Body / query | Notes |
| --- | --- | --- | --- |
| `GET` | `/me` | | `{user_id, username}` the token resolves to |
| `POST` | `/memories` | `{messages, agent_id?, run_id?, metadata?, infer?}` | `messages` is a string or `[{role, content}]`; `infer: false` stores verbatim, without the LLM |
| `GET` | `/memories` | `?agent_id&run_id&limit` | |
| `POST` | `/search` | `{query, agent_id?, run_id?, filters?, top_k?, threshold?, rerank?}` | `filters` is mem0's metadata filter syntax, ANDed with the caller |
| `GET` | `/memories/{id}` | | |
| `PUT` | `/memories/{id}` | `{text, metadata?}` | |
| `GET` | `/memories/{id}/history` | | |
| `DELETE` | `/memories/{id}` | | |
| `DELETE` | `/memories` | `?agent_id&run_id` | all of the caller's memories, or one agent's/run's |
| `GET` | `/healthz`, `/readyz` | | no auth, no backend calls |

The OpenAPI document is at `/docs`.

A per-project memory in an agent plugin is a `metadata` key, e.g.
`{"metadata": {"project": "owner/repo"}}` on add and `{"filters": {"project": "owner/repo"}}`
on search; `agent_id` separates tools (`opencode`, ...).

```sh
curl -s https://mem0.example.com/memories \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"I prefer tabs over spaces"}],"agent_id":"opencode","metadata":{"project":"hauke-cloud/infrastructure-flux"}}'
```

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `OIDC_ISSUER` | — | required |
| `OIDC_AUDIENCES` | — | required, comma separated; a token must name one |
| `OIDC_JWKS_URL` | discovery | |
| `OIDC_USER_ID_CLAIM` | `sub` | |
| `OIDC_REQUIRED_ROLES` | *(none)* | comma separated, any one suffices |
| `OIDC_ROLES_CLAIM` | `roles` | dotted path, e.g. `realm_access.roles` |
| `MEM0_LLM_BASE_URL`, `MEM0_LLM_MODEL` | — | required |
| `MEM0_LLM_API_KEY`, `MEM0_LLM_TEMPERATURE`, `MEM0_LLM_MAX_TOKENS` | `unused`, `0.1`, `2000` | |
| `MEM0_EMBEDDER_BASE_URL`, `MEM0_EMBEDDER_MODEL` | — | required |
| `MEM0_EMBEDDER_API_KEY`, `MEM0_EMBEDDING_DIMS` | `unused`, `1024` | dims must match the model |
| `PG_CONNECTION_STRING` | — | required, libpq URI or key=value |
| `MEM0_COLLECTION_NAME` | `memories` | table name |
| `MEM0_HISTORY_DB_PATH` | `/data/history.db` | |
| `MEM0_CONFIG_FILE` | | JSON deep-merged over the generated mem0 config |
| `AUTH_DISABLED`, `DEV_USER_ID` | `false`, `dev` | local development only |

The database needs `CREATE EXTENSION vector` run once by a superuser; mem0 creates its tables
itself.

## Deployment

The Helm chart is in [`deployment/helm/mem0-server`](deployment/helm/mem0-server) and is
published with the image on every release. See its `values.yaml` for the options.

## Development

```sh
make venv       # .venv with runtime and dev dependencies
make test
make ci-lint    # ruff, chart lint/render, values.yaml tag guard -- exactly what CI runs
make check      # format, then all of the above
```

Against a local pgvector without a token:

```sh
podman run -d --rm -p 5432:5432 -e POSTGRES_PASSWORD=pw -e POSTGRES_USER=mem0 pgvector/pgvector:pg17
AUTH_DISABLED=true MEM0_DIR=/tmp/mem0 MEM0_HISTORY_DB_PATH=/tmp/mem0/history.db \
  PG_CONNECTION_STRING=postgresql://mem0:pw@127.0.0.1/mem0 \
  MEM0_LLM_BASE_URL=http://127.0.0.1:8080/v1 MEM0_LLM_MODEL=... \
  MEM0_EMBEDDER_BASE_URL=http://127.0.0.1:8080/v1 MEM0_EMBEDDER_MODEL=... \
  PYTHONPATH=src .venv/bin/python -m mem0_server
```

## License

MIT
