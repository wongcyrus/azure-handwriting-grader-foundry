import hmac
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import jwt

from .errors import ApplicationError


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    object_id: str
    roles: frozenset[str]


class Authenticator(Protocol):
    def authenticate(self, token: str | None) -> Principal: ...


def unauthorized() -> ApplicationError:
    return ApplicationError("UNAUTHENTICATED", "A valid teacher access token is required.", 401)


class EntraAuthenticator:
    def __init__(self, tenant_id: str, audience: str, scope: str = "Exam.Access"):
        self.tenant_id = str(UUID(tenant_id))
        if not audience or not scope:
            raise ValueError("An API audience and delegated scope are required.")
        self.audience = audience
        self.scope = scope
        self.issuer = f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"
        self.keys = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{self.tenant_id}/discovery/v2.0/keys",
            timeout=10,
        )

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise unauthorized()
        try:
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "tid", "oid"]},
            )
            if not isinstance(claims["tid"], str) or not isinstance(claims["oid"], str):
                raise unauthorized()
            tenant = str(UUID(claims["tid"]))
            object_id = str(UUID(claims["oid"]))
            scopes = claims.get("scp")
            roles = claims.get("roles", [])
            if (
                tenant != self.tenant_id
                or claims.get("idtyp") == "app"
                or not isinstance(scopes, str)
                or self.scope not in scopes.split()
                or not isinstance(roles, list)
                or any(not isinstance(role, str) for role in roles)
            ):
                raise unauthorized()
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
            raise unauthorized() from error
        return Principal(tenant, object_id, frozenset(roles))


class DevelopmentAuthenticator:
    """Explicit local-only mode for synthetic data, never a production identity provider."""

    def __init__(self, token: str):
        if len(token) < 32:
            raise ValueError("FOUNDRY_DEV_TOKEN must contain at least 32 characters.")
        self.token = token

    def authenticate(self, token: str | None) -> Principal:
        if token is None or not hmac.compare_digest(token.encode(), self.token.encode()):
            raise unauthorized()
        return Principal(
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
            frozenset({"Teacher"}),
        )
