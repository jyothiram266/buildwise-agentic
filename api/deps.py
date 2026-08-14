"""Dependency injection for the HTTP layer.

The only place a request turns into an `AccessScope`. Every route depends on this
rather than reading a header itself, so there is exactly one code path where
identity becomes authorisation — which is what makes the ACL claim auditable.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from core.enums import APPROVER_ROLES
from core.errors import ScopeViolationError
from core.models import AccessScope
from governance import rbac


async def current_scope(
    authorization: Annotated[str | None, Header()] = None,
    x_actor_id: Annotated[str | None, Header()] = None,
) -> AccessScope:
    """Resolve the caller's scope from a bearer token.

    `X-Actor-Id` is accepted as a fallback for local development and the demo role
    switcher. It is refused when the app is running in prod mode, because a header
    that names your own identity is not authentication.
    """
    from api.config import get_settings

    if authorization and authorization.lower().startswith("bearer "):
        try:
            return await rbac.scope_from_token(authorization.split(" ", 1)[1].strip())
        except ScopeViolationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc

    if x_actor_id:
        if get_settings().app_env == "prod":
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "X-Actor-Id is a development convenience and is disabled in prod; send a bearer token",
            )
        try:
            return await rbac.scope_for_actor(x_actor_id)
        except ScopeViolationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, exc.message) from exc

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "no identity supplied; send Authorization: Bearer <token> or X-Actor-Id in dev",
    )


ScopeDep = Annotated[AccessScope, Depends(current_scope)]


async def approver_scope(scope: ScopeDep) -> AccessScope:
    """Gate for routes that act on the review queue."""
    if scope.role not in APPROVER_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"role {scope.role.value} may not act on review items",
        )
    return scope


ApproverDep = Annotated[AccessScope, Depends(approver_scope)]
