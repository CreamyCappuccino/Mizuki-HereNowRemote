"""Thin MCP/HTTP entrypoint. Runtime secrets and issuer registration stay external."""
from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.routes import build_resource_metadata_url, cors_middleware
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse
from starlette.routing import Route

from .here_now_http import ProviderHTTP, load_api_key
from .mcp_tools import register_tools
from .oauth_resource import READ_SCOPE, WRITE_SCOPE, OAuthConfig, OAuthVerifier
from .site_models import HereNowError
from .site_reader import SiteReader
from .site_update import SiteUpdater


def create_server(reader: SiteReader, *, oauth: OAuthConfig | None = None, verifier=None):
    auth = None if oauth is None else AuthSettings(issuer_url=AnyHttpUrl(oauth.issuer),
        resource_server_url=AnyHttpUrl(oauth.resource), required_scopes=[READ_SCOPE])
    server = MCPServer("Mizuki-HereNowRemote", version="0.1.0", auth=auth,
        token_verifier=(verifier or OAuthVerifier(oauth)) if oauth else None,
        instructions="Read versioned files, edit requested HTML/CSS/JS, then update_site_files. No CMS, approval queue, or filesystem access. Coordinate external publishers; site version checks are not atomic.")
    register_tools(server, reader, SiteUpdater(reader), oauth_enabled=oauth is not None)
    return server


def create_http_app(server, oauth: OAuthConfig):
    if oauth is None:
        raise HereNowError("oauth_config", "Remote HTTP requires OAuth configuration.")
    public = urlsplit(oauth.resource)
    app = server.streamable_http_app(stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[public.netloc, "localhost:*", "127.0.0.1:*"],
            allowed_origins=[f"{public.scheme}://{public.netloc}", "http://localhost:*", "http://127.0.0.1:*"]))
    path = build_resource_metadata_url(AnyHttpUrl(oauth.resource)).path
    async def metadata(request):
        return JSONResponse({"resource": oauth.resource, "authorization_servers": [oauth.issuer],
            "scopes_supported": [READ_SCOPE, WRITE_SCOPE], "bearer_methods_supported": ["header"]})
    matches = [i for i, route in enumerate(app.routes) if getattr(route, "path", None) == path]
    if len(matches) != 1:
        raise RuntimeError("SDK protected-resource metadata route differs from the verified contract.")
    app.routes[matches[0]] = Route(path, endpoint=cors_middleware(metadata, ["GET", "OPTIONS"]), methods=["GET", "OPTIONS"])
    return app


def main():
    parser = argparse.ArgumentParser(description="here.now file-editing MCP")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=4310)
    args = parser.parse_args()
    http = None
    try:
        oauth = OAuthConfig.from_env(os.environ) if args.transport == "streamable-http" else None
        if args.transport == "streamable-http" and oauth is None:
            raise HereNowError("oauth_config", "Set the OAuth issuer, resource and JWKS URLs before HTTP startup.")
        http = ProviderHTTP(load_api_key())
        reader = SiteReader(http)
        server = create_server(reader, oauth=oauth)
        if args.transport == "stdio":
            server.run(transport="stdio")
        else:
            import uvicorn
            uvicorn.run(create_http_app(server, oauth), host="127.0.0.1", port=args.port)
    except HereNowError as error:
        parser.exit(2, f"{error.code}: {error.message}\n")
    finally:
        if http is not None:
            http.close()


if __name__ == "__main__":
    main()
