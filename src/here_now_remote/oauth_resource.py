"""Resource-server JWT verification; use an existing OAuth issuer, not a new AS."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlsplit

import jwt

from .site_models import HereNowError

READ_SCOPE = "herenow:read"
WRITE_SCOPE = "herenow:write"


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    resource: str
    jwks_url: str

    def __post_init__(self):
        for value in (self.issuer, self.resource, self.jwks_url):
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment or url.query:
                raise HereNowError("oauth_config", "OAuth URLs must be absolute HTTPS URLs without userinfo/query/fragment.")
        if urlsplit(self.resource).path != "/mcp":
            raise HereNowError("oauth_config", "The resource URL must end in /mcp.")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> OAuthConfig | None:
        values = [env.get(k, "").strip() for k in ("HERENOW_OAUTH_ISSUER", "HERENOW_MCP_RESOURCE", "HERENOW_OAUTH_JWKS_URL")]
        if not any(values):
            return None
        if not all(values):
            raise HereNowError("oauth_config", "Set issuer, MCP resource and JWKS URL together.")
        return cls(*values)


def verified_claims(token: str, config: OAuthConfig, key_resolver: Callable) -> dict | None:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("typ") != "at+jwt" or not header.get("kid"):
            return None
        claims = jwt.decode(token, key_resolver(token), algorithms=["RS256"], issuer=config.issuer,
                            audience=config.resource, leeway=30,
                            options={"require": ["iss", "sub", "aud", "client_id", "scope", "iat", "exp", "jti"]})
        # Do not accept a multi-resource token just because this audience is in a list.
        if claims["aud"] != config.resource:
            return None
        if not all(isinstance(claims[k], str) and claims[k].strip() for k in ("sub", "client_id", "jti", "scope")):
            return None
        if not all(type(claims[k]) is int for k in ("iat", "exp")):
            return None
        return claims
    except (jwt.PyJWTError, TypeError, ValueError, OSError):
        return None


class OAuthVerifier:
    def __init__(self, config: OAuthConfig, key_resolver: Callable | None = None):
        self.config = config
        client = jwt.PyJWKClient(config.jwks_url, timeout=5, cache_jwk_set=True, lifespan=300,
                                headers={"User-Agent": "herenow-remote/0.1", "Accept": "application/json"})
        self._resolve = key_resolver or (lambda token: client.get_signing_key_from_jwt(token).key)

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        claims = await asyncio.to_thread(verified_claims, token, self.config, self._resolve)
        if claims is None:
            return None
        return AccessToken(token=token, client_id=claims["client_id"], scopes=claims["scope"].split(),
                           expires_at=claims["exp"], resource=self.config.resource,
                           subject=claims["sub"], claims=claims)
