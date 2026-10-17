"""New Site, provider history, and restore through an isolated fake HTTP service."""
import json

import httpx

from here_now_remote.here_now_http import ProviderHTTP
from here_now_remote.site_create import SiteCreator
from here_now_remote.site_models import HereNowError, TextChange, digest
from here_now_remote.site_reader import SiteReader
from here_now_remote.site_versions import SiteVersions
from conftest import FakeProvider


class LifecycleProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.created = None
        self.create_count = 0
        self.restore_count = 0

    def handle(self, req):
        path = req.url.path
        if req.url.host == "here.now" and req.method == "POST" and path == "/api/v1/publish":
            self.requests.append(req)
            assert req.headers["authorization"] == "Bearer test-key"
            self.create_count += 1
            payload = json.loads(req.content)
            assert payload["displayName"] == "Demo"
            self.create_manifest = payload["files"]
            uploads = [{"path": entry["path"], "method": "PUT", "url":
                        f"https://bucket.r2.cloudflarestorage.com/{entry['path']}?sig=x",
                        "headers": {"Content-Type": entry["contentType"], "x-amz-meta-test": "preserve-me"}} for entry in self.create_manifest]
            return httpx.Response(200, json={"slug": "test-created", "siteUrl": "https://test-created.here.now/",
                                             "upload": {"versionId": "v2", "uploads": uploads, "skipped": []}})
        if req.url.host == "here.now" and path == "/api/v1/publish/test-created/finalize":
            self.requests.append(req)
            assert req.method == "POST"
            self.created = {"slug": "test-created", "siteUrl": "https://test-created.here.now/",
                            "currentVersionId": "v2", "manifest": self.create_manifest}
            return httpx.Response(200, json={"success": True, "currentVersionId": "v2"})
        if req.url.host == "here.now" and path == "/api/v1/publish/test-created":
            self.requests.append(req)
            return httpx.Response(200 if self.created else 404, json=self.created or {})
        if req.url.host == "here.now" and path == "/api/v1/publish/test-site/versions":
            self.requests.append(req)
            return httpx.Response(200, json={"versions": [
                {"versionId": "v1", "createdAt": "2026-10-18", "source": "api"},
                {"versionId": "v0", "createdAt": "2026-10-17", "source": "editor"}]})
        if req.url.host == "here.now" and path == "/api/v1/publish/test-site/versions/v0/restore":
            self.requests.append(req)
            self.restore_count += 1
            self.version = "v0"
            return httpx.Response(200, json={"success": True, "currentVersionId": "v0"})
        return super().handle(req)


def test_create_and_readback():
    fake = LifecycleProvider()
    http = ProviderHTTP("test-key", transport=httpx.MockTransport(fake.handle))
    try:
        receipt = SiteCreator(SiteReader(http)).create([TextChange("index.html", "<h1>Demo</h1>")], "Demo")
        assert receipt.status == "published" and receipt.slug == "test-created"
        assert receipt.url == "https://test-created.here.now/" and receipt.uploaded == 1
        assert fake.create_count == 1
        assert fake.created["manifest"][0]["hash"] == digest(b"<h1>Demo</h1>")
        assert not any("authorization" in req.headers for req in fake.requests if req.url.host.endswith(".r2.cloudflarestorage.com"))
    finally:
        http.close()


def test_create_requires_root_index_before_network():
    fake = LifecycleProvider()
    http = ProviderHTTP("test-key", transport=httpx.MockTransport(fake.handle))
    try:
        try:
            SiteCreator(SiteReader(http)).create([TextChange("main.css", "body{}")])
            assert False, "Must reject missing index"
        except HereNowError as exc:
            assert exc.code == "missing_index"
        assert fake.requests == []
    finally:
        http.close()


def test_history_and_restore():
    fake = LifecycleProvider()
    http = ProviderHTTP("test-key", transport=httpx.MockTransport(fake.handle))
    try:
        versions = SiteVersions(SiteReader(http))
        current, rows = versions.list("test-site")
        assert current == "v1" and [r["versionId"] for r in rows] == ["v1", "v0"]
        changed = versions.restore("test-site", "v0", "v1")
        assert changed.status == "restored" and changed.current_version == "v0"
        assert fake.restore_count == 1
        try:
            versions.restore("test-site", "v1", "v1")
            assert False, "Must refuse a stale restore"
        except HereNowError as exc:
            assert exc.code == "version_conflict"
        assert fake.restore_count == 1
    finally:
        http.close()


def test_unknown_or_invalid_restore_version_stops_before_mutation():
    fake = LifecycleProvider()
    http = ProviderHTTP("test-key", transport=httpx.MockTransport(fake.handle))
    try:
        versions = SiteVersions(SiteReader(http))
        for wrong in ("not-in-list", "../v0"):
            try:
                versions.restore("test-site", wrong, "v1")
                assert False
            except HereNowError as exc:
                assert exc.code == "invalid_version"
        assert fake.restore_count == 0
    finally:
        http.close()
