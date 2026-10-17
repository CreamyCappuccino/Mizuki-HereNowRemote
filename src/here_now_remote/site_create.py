"""Create a new owned static Site through provider prepare/upload/finalize."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .site_models import HereNowError, SiteSnapshot, TextChange, merge_changes, validate_slug
from .site_reader import SiteReader
from .site_update import SiteUpdater


@dataclass(frozen=True)
class CreateReceipt:
    status: str
    slug: str | None = None
    url: str | None = None
    version: str | None = None
    uploaded: int = 0
    message: str = ""


class SiteCreator:
    def __init__(self, reader: SiteReader, *, max_change_bytes: int = 2 * 1024 * 1024):
        self.reader = reader
        self.http = reader.http
        self.max_change_bytes = max_change_bytes

    def create(self, files: list[TextChange], display_name: str | None = None) -> CreateReceipt:
        if display_name is not None and (not isinstance(display_name, str) or
                                         not 1 <= len(display_name.strip()) <= 80):
            raise HereNowError("invalid_name", "Site name must be 1-80 characters.")
        # Reuse the existing text-path/MIME/hash/byte-limit validation against an empty Site.
        empty = SiteSnapshot(slug="", version="", pending_version=None, files=())
        manifest, bodies = merge_changes(empty, files, max_bytes=self.max_change_bytes)
        if "index.html" not in manifest:
            raise HereNowError("missing_index", "A new website requires index.html at its root.")
        payload = {"files": [manifest[p].request_value() for p in sorted(manifest)]}
        if display_name is not None:
            payload["displayName"] = display_name.strip()
        try:
            prepared = self.http.json("POST", "/api/v1/publish", payload)
        except HereNowError:
            # A POST may have reached the provider even if its response was lost.
            return CreateReceipt("outcome_unknown", message="Create response unavailable. List sites before trying again.")

        slug = validate_slug(prepared.get("slug"))
        url = prepared.get("siteUrl")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (parsed is None or parsed.scheme != "https" or parsed.netloc != f"{slug}.here.now" or
                parsed.path != "/" or parsed.query or parsed.fragment):
            raise HereNowError("invalid_response", "Provider returned an unexpected Site URL.")
        upload = prepared.get("upload")
        if not isinstance(upload, dict) or not isinstance(upload.get("versionId"), str):
            raise HereNowError("invalid_response", "Create did not provide a pending version.")
        version = upload["versionId"]
        if not version:
            raise HereNowError("invalid_response", "Create returned an empty version.")
        receipt = CreateReceipt("not_published", slug=slug, url=url, version=version)
        try:
            uploads, skipped = SiteUpdater._upload_plan(upload, manifest)
            for target in uploads:
                self.http.upload(target, bodies[target["path"]])
            receipt = CreateReceipt("not_published", slug, url, version, len(uploads))
        except HereNowError as error:
            return CreateReceipt("not_published", slug, url, version, receipt.uploaded,
                                 f"Upload stopped ({error.code}); Site is not confirmed live.")
        try:
            # Canonical provider endpoint; never trust a returned finalizeUrl with our bearer.
            self.http.json("POST", f"/api/v1/publish/{slug}/finalize", {"versionId": version})
        except HereNowError:
            # The write may have completed. Verify via a separate readback.
            pass
        try:
            actual = self.reader.get_site(slug)
        except HereNowError:
            return CreateReceipt("outcome_unknown", slug, url, version, len(uploads),
                                 "Cannot verify the publication. Inspect this slug before another action.")
        if actual.version == version and actual.by_path == manifest:
            return CreateReceipt("published", slug, url, version, len(uploads),
                                 "Provider version and complete manifest verified.")
        return CreateReceipt("outcome_unknown", slug, url, version, len(uploads),
                             "The current Site does not match the prepared version; inspect before retrying.")