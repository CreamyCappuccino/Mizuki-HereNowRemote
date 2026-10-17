"""Runs with the actual MCP v2 SDK installed; no here.now account needed."""
import asyncio

import pytest

pytest.importorskip("mcp", reason="Install .[mcp,dev] to run actual SDK/HTTP tests")

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from here_now_remote.mcp_server import create_http_app, create_server
from here_now_remote.oauth_resource import OAuthConfig


def config():
    return OAuthConfig("https://auth.example.com", "https://mcp.example.com/mcp", "https://auth.example.com/jwks")


def test_four_tools_and_real_sdk_update(rig):
    fake, reader, _ = rig
    server = create_server(reader)
    async def run():
        tools = await server.list_tools()
        assert [t.name for t in tools] == ["list_sites", "get_site", "read_site_file", "update_site_files"]
        assert tools[-1].annotations.destructive_hint is True
        result = await server.call_tool("update_site_files", {"slug": fake.slug, "base_version_id": "v1",
            "changes": [{"path": "assets/style.css", "content": "h1 { color: red; }"}]})
        assert not result.is_error
        assert "published | test-site" in result.content[0].text
    asyncio.run(run())
    assert fake.finalize_count == 1


def test_remote_read_scope_cannot_write(rig):
    fake, reader, _ = rig
    server = create_server(reader, oauth=config())
    async def run():
        token = AccessToken(token="test", client_id="test", scopes=["herenow:read"], resource=config().resource)
        handle = auth_context_var.set(AuthenticatedUser(token))
        try:
            read = await server.call_tool("get_site", {"slug": fake.slug})
            assert not read.is_error
            result = await server.call_tool("update_site_files", {"slug": fake.slug, "base_version_id": "v1",
                "changes": [{"path": "index.html", "content": "new"}]})
            assert result.is_error and "insufficient_scope" in result.content[0].text
        finally:
            auth_context_var.reset(handle)
    asyncio.run(run())
    assert fake.prepare_count == 0


def test_http_metadata_and_anonymous_rejection(rig):
    _, reader, _ = rig
    oauth = config()
    server = create_server(reader, oauth=oauth)
    app = create_http_app(server, oauth)
    with TestClient(app, base_url="https://mcp.example.com") as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["scopes_supported"] == ["herenow:read", "herenow:write"]
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 401
