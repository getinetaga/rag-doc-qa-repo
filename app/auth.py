"""Per-user API keys and server-owned project permissions."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import config

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)
Role = Literal["read", "ingest", "admin"]


class ProjectScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    collection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

    @model_validator(mode="after")
    def reject_sentinels(self):
        if any(value.lower() == "default" for value in (self.tenant_id, self.collection_id)):
            raise ValueError("Project grants cannot use the default sentinel.")
        return self


class ApiUser(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: str = Field(min_length=1, max_length=128)
    key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$", exclude=True, repr=False)
    roles: frozenset[Role]
    scopes: tuple[ProjectScope, ...] = Field(min_length=1)
    default_scope: ProjectScope | None = None
    database_sources: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_grants(self):
        if not self.roles or len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Roles must be nonempty and project grants unique.")
        if self.default_scope is not None and self.default_scope not in self.scopes:
            raise ValueError("Default scope must be one of the project grants.")
        return self


class DatabaseSource(ProjectScope):
    dsn_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    table: str | None = None
    query: str | None = None
    max_rows: int = Field(default=5000, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_query(self):
        if bool(self.table) == bool(self.query):
            raise ValueError("A source must define exactly one table or query.")
        return self


class AccessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    users: tuple[ApiUser, ...] = Field(min_length=1)
    database_sources: dict[str, DatabaseSource] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_users(self):
        if len({user.user_id for user in self.users}) != len(self.users):
            raise ValueError("User IDs must be unique.")
        if len({user.key_sha256 for user in self.users}) != len(self.users):
            raise ValueError("API keys must be unique.")
        if any(not user.database_sources <= self.database_sources.keys() for user in self.users):
            raise ValueError("Database grants must reference configured sources.")
        return self


def load_policy() -> AccessPolicy:
    """Reload on every request so key/grant removal takes effect immediately."""
    try:
        if not config.RAG_API_USERS_FILE:
            raise ValueError("No access policy configured.")
        path = Path(config.RAG_API_USERS_FILE)
        if path.stat().st_size > 1_048_576:
            raise ValueError("Access policy is too large.")
        return AccessPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        logger.error("API access policy is unavailable or invalid.")
        raise HTTPException(503, "API access policy is unavailable.") from None


def authenticate_credentials(credentials: HTTPAuthorizationCredentials | None) -> ApiUser:
    if credentials is None or not 32 <= len(credentials.credentials) <= 512:
        raise HTTPException(401, "A valid personal API key is required.", headers={"WWW-Authenticate": "Bearer"})
    policy = load_policy()
    digest = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    matched = None
    for user in policy.users:
        if hmac.compare_digest(digest, user.key_sha256):
            matched = user
    if matched is None:
        logger.warning("API authentication rejected.")
        raise HTTPException(401, "A valid personal API key is required.", headers={"WWW-Authenticate": "Bearer"})
    return matched


def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiUser:
    user = getattr(request.state, "api_user", None)
    return user if user is not None else authenticate_credentials(credentials)


def require_role(user: ApiUser, role: Role) -> None:
    if role not in user.roles:
        raise HTTPException(403, "This action is not permitted.")


def authorize_scope(
    user: ApiUser, tenant_id: str | None, collection_id: str | None, *, role: Role = "read"
) -> ProjectScope:
    require_role(user, role)
    tenant = (tenant_id or "").strip()
    collection = (collection_id or "").strip()
    tenant = None if tenant.lower() in {"", "default"} else tenant
    collection = None if collection.lower() in {"", "default"} else collection
    matches = [
        scope for scope in user.scopes
        if (tenant is None or scope.tenant_id == tenant)
        and (collection is None or scope.collection_id == collection)
    ]
    if not matches:
        raise HTTPException(403, "This scope is not permitted.")
    if len(matches) == 1:
        return matches[0]
    if user.default_scope is not None and user.default_scope in matches:
        return user.default_scope
    raise HTTPException(422, "Select one permitted tenant and collection.")


async def authenticate_before_body(request: Request, call_next):
    if request.method != "OPTIONS" and request.url.path not in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}:
        from starlette.responses import JSONResponse

        try:
            request.state.api_user = authenticate_credentials(await _bearer(request))
            if request.url.path == "/upload":
                require_role(request.state.api_user, "ingest")
                declared = request.headers.get("content-length")
                if declared and int(declared) > config.MAX_UPLOAD_FILE_SIZE_BYTES + 1_048_576:
                    raise HTTPException(413, "Request exceeds the upload size limit.")
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
    return await call_next(request)


def approved_database_source(user: ApiUser, source_id: str, scope: ProjectScope) -> DatabaseSource:
    require_role(user, "ingest")
    source = load_policy().database_sources.get(source_id)
    if (
        source_id not in user.database_sources or source is None
        or source.tenant_id != scope.tenant_id or source.collection_id != scope.collection_id
    ):
        raise HTTPException(403, "This database source is not permitted.")
    return source


def authorize_current_user(user_id: str, tenant_id: str, collection_id: str, *, role: Role = "read") -> None:
    user = next((user for user in load_policy().users if user.user_id == user_id), None)
    if user is None:
        raise HTTPException(403, "This action is no longer permitted.")
    authorize_scope(user, tenant_id, collection_id, role=role)


def database_connection(source: DatabaseSource) -> str:
    value = os.getenv(source.dsn_env)
    if not value:
        logger.error("An approved database source is not configured.")
        raise HTTPException(503, "Database source is unavailable.")
    return value


def require_service_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    token = config.RAG_SERVICE_TOKEN
    if not token or len(token) < 32:
        raise HTTPException(503, "Service authentication is not configured.")
    if credentials is None or not hmac.compare_digest(credentials.credentials.encode("utf-8"), token.encode("utf-8")):
        raise HTTPException(401, "Service authentication required.", headers={"WWW-Authenticate": "Bearer"})
