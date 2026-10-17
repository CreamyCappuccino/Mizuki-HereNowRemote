"""Provider HTTP boundary: credentials never leave the canonical API origin."""
from __future__ import annotations

import os
from contextlib import closing
import stat
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .site_models import HereNowError

API_BASE = "https://here.now"


def load_api_key() -> str:
    value = os.environ.get("HERENOW_API_KEY", "").strip()
    if value:
        return value
    path = Path(os.environ.get("HERENOW_CREDENTIALS_FILE", "~/.herenow/credentials")).expanduser()
    if path.is_symlink():
        raise HereNowError("credentials", "Credentials must not be a symlink.")
    try:
        with path.open() as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise HereNowError("credentials", "Credentials must be an owner-only regular file (0600).")
            value = stream.read().strip()
    except OSError as error:
        raise HereNowError("credentials", "Set HERENOW_API_KEY or configure an owner-only credential file.") from error
    if not value or any(c.isspace() for c in value):
        raise HereNowError("credentials", "Credentials are empty or malformed.")
    return value


class ProviderHTTP:
    def __init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key or any(c.isspace() for c in api_key):
            raise HereNowError("credentials", "An API key is required.")
        self._key = api_key
        # No default Authorization, cookies, environment proxy or automatic redirects.
        self._client = httpx.Client(transport=transport, timeout=30.0, follow_redirects=False, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _send(self, method: str, url: str, *, stage: str, max_bytes: int, **kwargs) -> bytes:
        try:
            request = self._client.build_request(method, url, **kwargs)
            request.headers.pop("cookie", None)
            with closing(self._client.send(request, stream=True)) as response:
                if not 200 <= response.status_code < 300:
                    status = response.status_code
                    code = "version_conflict" if status == 409 else f"http_{status}"
                    wait = response.headers.get("retry-after", "")
                    hint = f" Retry after {wait} seconds." if wait.isdecimal() else ""
                    raise HereNowError(code, f"Provider returned HTTP {status}.{hint}", stage=stage)
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise HereNowError("too_large", "Response exceeds the configured byte limit.", stage=stage)
                return bytes(body)
        except httpx.HTTPError as error:
            raise HereNowError("network_error", "Provider response was not received; no automatic write retry.", stage=stage) from error

    def json(self, method: str, path: str, payload: dict | None = None) -> dict:
        import json

        if not path.startswith("/api/v1/") or any(c in path for c in ("?", "#", "\\")):
            raise HereNowError("invalid_endpoint", "Invalid provider API path.")
        headers = {"Authorization": f"Bearer {self._key}", "X-HereNow-Client": "chatgpt/herenow-remote"}
        kwargs = {"headers": headers}
        if payload is not None:
            kwargs["json"] = payload
        raw = self._send(method, API_BASE + path, stage=path.rsplit("/", 1)[-1], max_bytes=4 * 1024 * 1024, **kwargs)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise HereNowError("invalid_response", "Provider returned invalid JSON.") from error
        if not isinstance(value, dict) or value.get("error") or value.get("success") is False:
            raise HereNowError("invalid_response", "Provider did not return a successful object.")
        return value

    def file_bytes(self, slug: str, encoded_path: str, *, max_bytes: int) -> bytes:
        return self._send("GET", f"{API_BASE}/api/v1/publish/{slug}/files/{encoded_path}",
                          stage="read_file", max_bytes=max_bytes,
                          headers={"Authorization": f"Bearer {self._key}",
                                   "X-HereNow-Client": "chatgpt/herenow-remote"})

    def upload(self, target: dict, content: bytes) -> None:
        url = target.get("url")
        if not isinstance(url, str):
            raise HereNowError("invalid_upload", "Upload URL missing.", stage="upload")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".r2.cloudflarestorage.com")
                or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
            raise HereNowError("invalid_upload", "Upload destination is not an HTTPS R2 endpoint.", stage="upload")
        headers = target.get("headers")
        if target.get("method") != "PUT" or not isinstance(headers, dict):
            raise HereNowError("invalid_upload", "Upload method/headers missing.", stage="upload")
        forbidden = {"authorization", "proxy-authorization", "cookie", "host"}
        if any(not isinstance(k, str) or not isinstance(v, str) or k.lower() in forbidden for k, v in headers.items()):
            raise HereNowError("invalid_upload", "Unexpected credential/routing upload header.", stage="upload")
        self._send("PUT", url, stage="upload", max_bytes=1024 * 1024, headers=headers, content=content)
