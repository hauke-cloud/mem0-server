<!-- llm-readme-management spec=1 commit=c267d1ae20178ce5bcd37f13f0484989eae34104 template=python model=qwen3.8-27b-q4 digest=08ee779219f6 generated=2026-10-12T08:48:50Z -->
<a href="https://hauke.cloud" target="_blank"><img src="https://img.shields.io/badge/home-hauke.cloud-brightgreen" alt="hauke.cloud" style="display: block;" /></a>
<a href="https://github.com/hauke-cloud" target="_blank"><img src="https://img.shields.io/badge/github-hauke.cloud-blue" alt="hauke.cloud Github Organisation" style="display: block;" /></a>
<a href="https://github.com/hauke-cloud/llm-readme-management" target="_blank"><img src="https://img.shields.io/badge/template-python-orange" alt="Repository type - python" style="display: block;" /></a>


# Mem0 Server


<img src="https://raw.githubusercontent.com/hauke-cloud/.github/main/resources/img/organisation-logo-small.png" alt="hauke.cloud logo" width="109" height="123" align="right">


<llm header hint="Name the distribution and say whether it is a library, a CLI or a service.">

A Python FastAPI service that exposes the mem0 memory library as a REST API, deriving the caller's `user_id` from a verified OIDC access token so each client only ever touches its own memories. You deploy it as a container image or Helm chart in front of self-hosted OpenAI-compatible model servers.

</llm>


## :book: Description

<llm description>

The stock mem0 server accepts `user_id` from the request body, so any client can read or write any user's memories. This repository wraps mem0 behind a FastAPI REST API that derives the caller's identity from a verified OIDC access token (JWKS, asymmetric algorithms only), scoping every operation to that user. A caller cannot list, search, or address another user's memories; foreign IDs return 404 and reserved metadata keys are rejected with 400.

The service is deployed as a container image or Helm chart in front of a Postgres/pgvector database and an OpenAI-compatible LLM and embedder endpoint (for example behind llama-swap). Agent plugins such as the opencode memory plugin and other HTTP clients consume the API.

- Add, list, search, read, update, and delete memories; per-memory change history
- OIDC bearer-token authentication with optional role-based access control via a configurable claim path
- Per-user isolation on every endpoint; bulk delete scoped by `agent_id`/`run_id`
- Health and readiness probes that never touch Postgres, the LLM, or the embedder
- Helm chart with optional Ingress, Gateway API HTTPRoute, and Envoy Gateway SecurityPolicy/BackendTrafficPolicy

</llm>


## :clipboard: Requirements

<llm requirements hint="Give the Python version from requires-python or the CI matrix, and name the packaging tool actually in use (uv, poetry, pip).">

- Python ≥ 3.11 (3.13 in CI and container images); dependencies installed with pip from `requirements.txt` / `requirements-dev.txt`.
- A container engine (Docker or Podman) for `make image`.
- Helm for chart linting and templating (`make helm-lint`).
- PostgreSQL with the `pgvector` extension installed (`CREATE EXTENSION vector`); suggested dev image: `pgvector/pgvector:pg17`.
- An OIDC identity provider reachable over HTTPS for JWKS token verification, or `AUTH_DISABLED=true` for local development.
- One OpenAI-compatible chat-completions endpoint and one embeddings endpoint (e.g. behind llama-swap).
- A Kubernetes cluster for deploying the Helm chart; Envoy Gateway (Gateway API) only if you enable the optional `httpRoute` or Envoy Gateway policies.
- For CI releases: GitHub Actions write permissions on `contents`, `packages`, and `id-token` to push the image and chart to GHCR.

</llm>


## 🚀 Getting started

<llm getting_started hint="Use the project's real installation path -- editable install, uv sync, poetry install -- not a generic pip install.">
</llm>


## :airplane: Usage

<llm usage hint="Show the console-script entry points by name if the packaging metadata defines any.">
</llm>


## :wrench: Configuration

<llm configuration>

All service configuration is read from environment variables at startup (`Settings.from_env` in `src/mem0_server/config.py`). The table below covers the variables you will set in practice; the full list lives in that file.

| Name | Default | Description |
|------|---------|-------------|
| `OIDC_ISSUER` | — (required) | OIDC issuer URL; used for JWKS discovery |
| `OIDC_AUDIENCES` | — (required) | Comma-separated audience values the token must name |
| `MEM0_LLM_BASE_URL` | — (required) | OpenAI-compatible chat endpoint |
| `MEM0_LLM_MODEL` | — (required) | Chat model name |
| `MEM0_EMBEDDER_BASE_URL` | — (required) | OpenAI-compatible embeddings endpoint |
| `MEM0_EMBEDDER_MODEL` | — (required) | Embeddings model name |
| `PG_CONNECTION_STRING` | — (required) | libpq URI or key=value string for Postgres |
| `AUTH_DISABLED` | `false` | When `true`, all requests act as `DEV_USER_ID` (default `dev`); local development only |
| `OIDC_USER_ID_CLAIM` | `sub` | JWT claim used as the caller's `user_id` |
| `OIDC_ROLES_CLAIM` | `roles` | Dotted path to the roles claim (e.g. `realm_access.roles`) |
| `OIDC_REQUIRED_ROLES` | *(none)* | Comma-separated roles; the token must carry at least one |
| `MEM0_EMBEDDING_DIMS` | `1024` | Vector dimensionality; must match the embedder model |
| `MEM0_COLLECTION_NAME` | `memories` | pgvector collection name |
| `MEM0_HISTORY_DB_PATH` | `/data/history.db` | SQLite path for mem0 change history |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address and port |
| `LOG_LEVEL` | `info` | Uvicorn log level |

The Helm chart (`deployment/helm/mem0-server/values.yaml`) mirrors these as `oidc.*`, `mem0.*`, and `postgres.*` values and adds deployment-level options (persistence, ingress, Envoy Gateway policies, resource limits).

</llm>


## :hammer: Development

<llm development hint="Cover the test runner, the linter and any pre-commit hooks the repository configures.">

Set up a virtual environment and install dependencies:

```bash
make venv
```

Run the test suite (no network, no Postgres, no real mem0):

```bash
make test
```

Format and lint with Ruff (target `py311`, line length 120):

```bash
make fmt
```

CI runs `make ci-lint`, which chains `fmt-check`, `lint`, `helm-lint`, and `tag-guard`. The full local equivalent is:

```bash
make check
```

This formats first, then runs every check CI performs. `helm-lint` requires the `helm` binary and renders the chart with all optional features enabled. `tag-guard` fails if `deployment/helm/mem0-server/values.yaml` does not contain exactly one `tag:` line, because CI rewrites that line from the git tag on release.

Pull request titles are validated by a semantic-commit check. Allowed types are `fix`, `feat`, `docs`, `ci`, `chore`; the subject must start with an uppercase letter.

</llm>


## 📄 License

This Project is licensed under the GNU General Public License v3.0

- see the [LICENSE](LICENSE) file for details.


## :coffee: Contributing

To become a contributor, please check out the [CONTRIBUTING](CONTRIBUTING.md) file.


## :email: Contact

For any inquiries or support requests, please open an issue in this
repository or contact us at [contact@hauke.cloud](mailto:contact@hauke.cloud).
