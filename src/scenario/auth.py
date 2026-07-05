"""Development auth primitives for scenario-facing APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, cast


PrincipalRole = Literal["keeper", "player", "observer", "service"]

PERMISSION_VIEW_PUBLIC = "view_public"
PERMISSION_VIEW_PLAYER = "view_player"
PERMISSION_VIEW_KEEPER = "view_keeper"
PERMISSION_SERVICE_TASK = "service_task"

_VALID_ROLES: frozenset[str] = frozenset(
    {"keeper", "player", "observer", "service"}
)
_DEFAULT_ROLE_PERMISSIONS: Mapping[PrincipalRole, frozenset[str]] = {
    "keeper": frozenset(
        {PERMISSION_VIEW_PUBLIC, PERMISSION_VIEW_PLAYER, PERMISSION_VIEW_KEEPER}
    ),
    "player": frozenset({PERMISSION_VIEW_PUBLIC, PERMISSION_VIEW_PLAYER}),
    "observer": frozenset({PERMISSION_VIEW_PUBLIC}),
    "service": frozenset({PERMISSION_SERVICE_TASK}),
}


@dataclass(frozen=True)
class Principal:
    """Authenticated actor scoped to one session or an offline service task."""

    principal_id: str
    role: PrincipalRole
    session_id: str | None = None
    player_id: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.role not in _VALID_ROLES:
            raise ValueError(f"未知 principal role: {self.role}")
        if not self.principal_id:
            raise ValueError("principal_id 不能为空")
        permissions = (
            _DEFAULT_ROLE_PERMISSIONS[self.role]
            if not self.permissions
            else frozenset(self.permissions)
        )
        object.__setattr__(self, "permissions", permissions)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


class AuthError(PermissionError):
    """Base auth error with an HTTP-ish status code."""

    status_code = 403
    error_code = "authorization_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AuthenticationRequired(AuthError):
    status_code = 401
    error_code = "authentication_required"


class AuthorizationDenied(AuthError):
    status_code = 403
    error_code = "authorization_denied"


DEV_TOKEN_REGISTRY: dict[str, Principal] = {}


def auth_error_payload(error: AuthError) -> dict[str, object]:
    return {"error": str(error), "code": error.error_code}


def parse_authorization_header(
    authorization: str | None,
    *,
    registry: Mapping[str, Principal] | None = None,
    required: bool = True,
) -> Principal | None:
    """Parse an ``Authorization: Bearer <dev-token>`` header."""

    if authorization is None or not authorization.strip():
        if required:
            raise AuthenticationRequired("缺少 Authorization Bearer token")
        return None

    scheme, separator, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise AuthenticationRequired("Authorization 必须使用 Bearer token")
    if " " in token.strip():
        raise AuthenticationRequired("Bearer token 不能包含空格")
    return parse_dev_token(token.strip(), registry=registry)


def parse_dev_token(
    token: str,
    *,
    registry: Mapping[str, Principal] | None = None,
) -> Principal:
    """Parse the local dev token format.

    Format:
    ``dev:<role>:<principal_id>[:<session_id>[:<player_id>[:<permissions>]]]``

    ``-`` or an empty field means "not scoped". ``permissions`` is a
    comma-separated list such as ``view_player,view_keeper``. Omitted
    permissions fall back to role defaults.
    """

    token_registry = registry if registry is not None else DEV_TOKEN_REGISTRY
    registered = token_registry.get(token)
    if registered is not None:
        return registered

    parts = token.split(":")
    if len(parts) < 3 or len(parts) > 6 or parts[0] != "dev":
        raise AuthenticationRequired("无法解析 dev token")

    role = parts[1]
    if role not in _VALID_ROLES:
        raise AuthenticationRequired(f"未知 dev token role: {role}")
    principal_id = parts[2]
    if not principal_id:
        raise AuthenticationRequired("dev token 缺少 principal_id")

    session_id = _optional_token_field(parts[3]) if len(parts) >= 4 else None
    player_id = _optional_token_field(parts[4]) if len(parts) >= 5 else None
    permissions = (
        _parse_permissions(parts[5])
        if len(parts) >= 6 and _optional_token_field(parts[5]) is not None
        else frozenset()
    )
    return Principal(
        principal_id=principal_id,
        role=cast(PrincipalRole, role),
        session_id=session_id,
        player_id=player_id,
        permissions=permissions,
    )


def principal_from_requester_id(
    requester_id: str,
    *,
    session_id: str,
    owner_id: str,
) -> Principal:
    """Adapt the legacy requester_id contract into a Principal."""

    if requester_id == owner_id:
        return Principal(
            principal_id=requester_id,
            role="keeper",
            session_id=session_id,
        )
    return Principal(
        principal_id=requester_id,
        role="player",
        session_id=session_id,
        player_id=requester_id,
    )


def authorize_public_view(
    principal: Principal | None,
    *,
    session_id: str,
) -> None:
    principal = require_principal(principal)
    _ensure_session_scope(principal, session_id)
    if not principal.has_permission(PERMISSION_VIEW_PUBLIC):
        raise AuthorizationDenied(f"{principal.principal_id} 无权查看公开视图")


def authorize_player_view(
    principal: Principal | None,
    *,
    session_id: str,
    target_player_id: str,
) -> None:
    principal = require_principal(principal)
    _ensure_session_scope(principal, session_id)
    if not principal.has_permission(PERMISSION_VIEW_PLAYER) and not (
        principal.role == "service" and principal.has_permission(PERMISSION_SERVICE_TASK)
    ):
        raise AuthorizationDenied(
            f"玩家 {principal.principal_id} 无权查看玩家 {target_player_id} 的会话视图"
        )
    if principal.role == "keeper":
        return
    if principal.role == "service" and principal.has_permission(
        PERMISSION_SERVICE_TASK
    ):
        return
    if principal.role == "player" and principal.player_id == target_player_id:
        return
    raise AuthorizationDenied(
        f"玩家 {principal.principal_id} 无权查看玩家 {target_player_id} 的会话视图"
    )


def authorize_keeper_view(
    principal: Principal | None,
    *,
    session_id: str,
) -> None:
    principal = require_principal(principal)
    _ensure_session_scope(principal, session_id)
    if not principal.has_permission(PERMISSION_VIEW_KEEPER):
        if not (
            principal.role == "service"
            and principal.has_permission(PERMISSION_SERVICE_TASK)
        ):
            raise AuthorizationDenied(
                f"玩家 {principal.principal_id} 无权查看守密人视图"
            )
    if principal.role in {"keeper", "service"}:
        return
    raise AuthorizationDenied(f"玩家 {principal.principal_id} 无权查看守密人视图")


def ensure_service_task_access(
    principal: Principal | None,
    *,
    session_id: str | None = None,
) -> None:
    principal = require_principal(principal)
    if session_id is not None:
        _ensure_session_scope(principal, session_id)
    if principal.role != "service" or not principal.has_permission(
        PERMISSION_SERVICE_TASK
    ):
        raise AuthorizationDenied(f"{principal.principal_id} 无权执行离线服务任务")


def require_principal(principal: Principal | None) -> Principal:
    if principal is None:
        raise AuthenticationRequired("缺少 Authorization Bearer token")
    return principal


def _ensure_session_scope(principal: Principal, session_id: str) -> None:
    if principal.session_id is not None and principal.session_id != session_id:
        raise AuthorizationDenied(
            f"{principal.principal_id} 无权访问会话 {session_id}"
        )


def _optional_token_field(value: str) -> str | None:
    stripped = value.strip()
    if not stripped or stripped == "-":
        return None
    return stripped


def _parse_permissions(value: str) -> frozenset[str]:
    return frozenset(
        permission.strip()
        for permission in value.split(",")
        if permission.strip() and permission.strip() != "-"
    )
