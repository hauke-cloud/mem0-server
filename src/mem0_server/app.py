"""REST API over a mem0 Memory, scoped to the caller's OIDC identity.

The request shapes follow mem0's own self-hosted server (POST /memories,
POST /search, ...) so existing clients need little change, with one
difference: there is no user_id parameter. The user_id is always the verified
token's subject, and every memory addressed by id is checked to belong to it.
A memory owned by someone else answers 404, exactly like one that does not
exist, so ids cannot be probed.
"""

# No `from __future__ import annotations`: FastAPI resolves dependency
# annotations at runtime, and CurrentUser is local to create_app.
import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, ForbiddenError, Principal, TokenVerifier
from .config import Settings

logger = logging.getLogger(__name__)

# Payload keys mem0 manages itself. Letting a caller set them through metadata
# could file a memory under another user (user_id) or corrupt mem0's own
# bookkeeping (hash, timestamps).
RESERVED_KEYS = frozenset(
    {"user_id", "agent_id", "run_id", "actor_id", "data", "hash", "created_at", "updated_at", "text_lemmatized"}
)

EntityId = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:@/-]+$")]


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] | str
    agent_id: EntityId | None = None
    run_id: EntityId | None = None
    metadata: dict[str, Any] | None = None
    # False stores the messages verbatim, without the LLM extraction step.
    infer: bool = True


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    agent_id: EntityId | None = None
    run_id: EntityId | None = None
    # mem0 filter syntax on metadata (eq, in, gte, AND/OR/NOT, ...). ANDed with
    # the caller's user_id, so it can only narrow the caller's own memories.
    filters: dict[str, Any] | None = None
    top_k: int = Field(10, ge=1, le=100)
    threshold: float | None = Field(None, ge=0, le=1)
    rerank: bool = False


def _reject_reserved(value: Any, where: str) -> None:
    """Refuse reserved keys anywhere in a caller-supplied dict tree."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in RESERVED_KEYS:
                raise HTTPException(status_code=400, detail=f"{where} must not contain {key!r}")
            _reject_reserved(child, where)
    elif isinstance(value, list):
        for child in value:
            _reject_reserved(child, where)


def _scope(principal: Principal, agent_id: str | None, run_id: str | None) -> dict[str, str]:
    scope = {"user_id": principal.user_id}
    if agent_id:
        scope["agent_id"] = agent_id
    if run_id:
        scope["run_id"] = run_id
    return scope


def create_app(
    settings: Settings,
    memory_factory: Callable[[], Any] | None = None,
    verifier: TokenVerifier | None = None,
) -> FastAPI:
    state: dict[str, Any] = {"memory": None}
    init_lock = threading.Lock()

    if memory_factory is None:

        def memory_factory() -> Any:
            from mem0 import Memory

            return Memory.from_config(settings.mem0_config())

    if verifier is None and not settings.auth_disabled:
        verifier = TokenVerifier(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.auth_disabled:
            logger.warning("AUTH_DISABLED is set: every request acts as user %r", settings.dev_user_id)
        yield

    app = FastAPI(
        title="mem0-server",
        description="Per-user mem0 memory API behind OIDC",
        lifespan=lifespan,
    )

    def memory() -> Any:
        # Built on first use rather than at startup: constructing it connects
        # to Postgres, and a pod that crash-loops on a database hiccup is worse
        # than one that answers 503 until the database is back.
        if state["memory"] is None:
            with init_lock:
                if state["memory"] is None:
                    try:
                        state["memory"] = memory_factory()
                    except Exception as exc:
                        logger.exception("mem0 initialisation failed")
                        raise HTTPException(status_code=503, detail="memory store unavailable") from exc
        return state["memory"]

    def principal(request: Request) -> Principal:
        if settings.auth_disabled:
            return Principal(user_id=settings.dev_user_id)
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        # "Token" is what mem0's own clients send; accepted as an alias.
        if scheme.lower() not in {"bearer", "token"} or not token.strip():
            raise HTTPException(status_code=401, detail="bearer token required", headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.verify(token.strip())
        except AuthError as exc:
            raise HTTPException(
                status_code=401, detail=str(exc), headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}
            ) from exc
        except ForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    CurrentUser = Annotated[Principal, Depends(principal)]

    def owned(memory_id: str, user: Principal) -> dict[str, Any]:
        try:
            item = memory().get(memory_id)
        except ValueError:
            item = None
        if not item or item.get("user_id") != user.user_id:
            raise HTTPException(status_code=404, detail="memory not found")
        return item

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:
        # Deliberately does not call the LLM or embedder: behind llama-swap
        # that would load (and possibly swap in) a model on every probe.
        return {"status": "ok"}

    @app.get("/me", summary="The identity memories are filed under")
    def me(user: CurrentUser) -> dict[str, Any]:
        return {"user_id": user.user_id, "username": user.username}

    @app.post("/memories", summary="Add memories from messages")
    def add_memory(body: MemoryCreate, user: CurrentUser) -> Any:
        _reject_reserved(body.metadata, "metadata")
        messages = body.messages if isinstance(body.messages, str) else [m.model_dump() for m in body.messages]
        return memory().add(
            messages,
            **_scope(user, body.agent_id, body.run_id),
            metadata=body.metadata,
            infer=body.infer,
        )

    @app.get("/memories", summary="List the caller's memories")
    def list_memories(
        user: CurrentUser,
        agent_id: Annotated[str | None, Query(max_length=200)] = None,
        run_id: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> Any:
        return memory().get_all(filters=_scope(user, agent_id, run_id), top_k=limit)

    @app.post("/search", summary="Semantic search over the caller's memories")
    def search(body: SearchRequest, user: CurrentUser) -> Any:
        _reject_reserved(body.filters, "filters")
        # Caller filters first, identity last: on any key clash the identity wins.
        filters = {**(body.filters or {}), **_scope(user, body.agent_id, body.run_id)}
        kwargs: dict[str, Any] = {"filters": filters, "top_k": body.top_k, "rerank": body.rerank}
        if body.threshold is not None:
            kwargs["threshold"] = body.threshold
        return memory().search(body.query, **kwargs)

    @app.get("/memories/{memory_id}", summary="Get one memory")
    def get_memory(memory_id: str, user: CurrentUser) -> Any:
        return owned(memory_id, user)

    @app.put("/memories/{memory_id}", summary="Replace a memory's text")
    def update_memory(memory_id: str, body: MemoryUpdate, user: CurrentUser) -> Any:
        _reject_reserved(body.metadata, "metadata")
        owned(memory_id, user)
        return memory().update(memory_id, text=body.text, metadata=body.metadata)

    @app.get("/memories/{memory_id}/history", summary="Change history of a memory")
    def memory_history(memory_id: str, user: CurrentUser) -> Any:
        owned(memory_id, user)
        return memory().history(memory_id)

    @app.delete("/memories/{memory_id}", summary="Delete a memory")
    def delete_memory(memory_id: str, user: CurrentUser) -> dict[str, str]:
        owned(memory_id, user)
        memory().delete(memory_id)
        return {"message": "memory deleted"}

    @app.delete("/memories", summary="Delete all of the caller's memories (optionally one agent/run)")
    def delete_all(
        user: CurrentUser,
        agent_id: Annotated[str | None, Query(max_length=200)] = None,
        run_id: Annotated[str | None, Query(max_length=200)] = None,
    ) -> dict[str, str]:
        memory().delete_all(**_scope(user, agent_id, run_id))
        return {"message": "memories deleted"}

    return app
