"""In-memory provider, exercising real HTTP requests without publishing anything."""
from __future__ import annotations

import json
from copy import deepcopy
from urllib.parse import unquote

import httpx
import pytest

from here_now_remote.here_now_http import ProviderHTTP
from here_now_remote.site_models import digest
from here_now_remote.site_reader import SiteReader
from here_now_remote.site_update import SiteUpdater


class FakeProvider:
    slug = "test-site"

    def __init__(self):
        self.version = "v1"
        self.pending = None
        self.bodies = {"index.html": b"<h1>Hello</h1>", "assets/style.css": b"h1 { font-size: 20px; }"}
        self.manifest = [{"path": p, "size": len(b), "contentType": "text/css" if p.endswith(".css") else "text/html",
                          "hash": digest(b)} for p, b in sorted(self.bodies.items())]
        self.requests = []
        self.next_manifest = None
        self.uploads = {}
        self.finalize_count = 0
        self.prepare_count = 0
        self.finalize_timeout = False
        self.upload_failure = False
        self.after_prepare_change = False
        self.read_drift = False
        self.corrupt_read = False
        self.bad_targets = False
        self.force_upload_all = False
        self.finalize_readback_error = False

    def details(self):
        return {"slug": self.slug, "siteUrl": f"https://{self.slug}.here.now/", "status": "active",
                "currentVersionId": self.version, "pendingVersionId": self.pending, "manifest": deepcopy(self.manifest)}

    def handle(self, req):
        self.requests.append(req)
        host, path = req.url.host, req.url.path
        if host == "here.now":
            assert req.headers["authorization"] == "Bearer test-key"
            if path == "/api/v1/publishes":
                return httpx.Response(200, json={"publishes": [self.details()]})
            if req.method == "GET":
                if self.finalize_readback_error and self.finalize_count:
                    raise httpx.ReadTimeout("test", request=req)
                return httpx.Response(200, json=self.details())
            if req.method == "PUT":
                self.prepare_count += 1
                payload = json.loads(req.content)
                assert set(payload) == {"files"}  # No undocumented precondition or setting reset.
                self.next_manifest = payload["files"]
                self.pending = "v2"
                existing = {e["path"]: e["hash"] for e in self.manifest}
                needed = [e["path"] for e in self.next_manifest if self.force_upload_all or existing.get(e["path"]) != e["hash"]]
                targets = [{"path": p, "method": "PUT", "url": f"https://bucket.r2.cloudflarestorage.com/{p}?sig=secret",
                            "headers": {"Content-Type": next(e["contentType"] for e in self.next_manifest if e["path"] == p),
                                        "x-amz-meta-test": "preserve-me"}} for p in needed]
                skipped = [e["path"] for e in self.next_manifest if e["path"] not in needed]
                if self.bad_targets:
                    targets = []
                if self.after_prepare_change:
                    self.version = "external-v3"
                return httpx.Response(200, json={"upload": {"versionId": self.pending, "uploads": targets,
                    "skipped": skipped, "finalizeUrl": "https://untrusted.example/finalize", "expiresInSeconds": 3600}})
            if path.endswith("/finalize"):
                self.finalize_count += 1
                assert json.loads(req.content) == {"versionId": "v2"}
                self.manifest = deepcopy(self.next_manifest)
                self.bodies.update(self.uploads)
                self.version, self.pending = "v2", None
                if self.finalize_timeout:
                    raise httpx.ReadTimeout("secret URL must not leak", request=req)
                return httpx.Response(200, json={"success": True, "currentVersionId": "v2"})
        assert "authorization" not in req.headers
        if host.endswith(".r2.cloudflarestorage.com"):
            assert req.headers["x-amz-meta-test"] == "preserve-me"
            if self.upload_failure:
                return httpx.Response(503)
            self.uploads[unquote(path.lstrip("/"))] = req.content
            return httpx.Response(200)
        if host == "test-site.here.now":
            if self.read_drift:
                self.version = "v3"
            data = self.bodies.get(unquote(path.lstrip("/")))
            return httpx.Response(200 if data is not None else 404, content=b"wrong" if self.corrupt_read else data)
        raise AssertionError(f"Unexpected HTTP request {req.method} {host} {path}")


@pytest.fixture
def rig():
    fake = FakeProvider()
    http = ProviderHTTP("test-key", transport=httpx.MockTransport(fake.handle))
    reader = SiteReader(http)
    yield fake, reader, SiteUpdater(reader)
    http.close()
