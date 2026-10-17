"""Read provider metadata and hash-checked public bytes, not guessed owner APIs."""
from __future__ import annotations

from urllib.parse import quote

from .here_now_http import ProviderHTTP
from .site_models import FileEntry, HereNowError, SiteSnapshot, is_text, validate_path, validate_slug


class SiteReader:
    def __init__(self, http: ProviderHTTP, *, max_file_bytes: int = 1024 * 1024) -> None:
        self.http = http
        self.max_file_bytes = max_file_bytes

    def list_sites(self) -> list[dict]:
        # Omit scope: the documented default is the key owner's personal account.
        values = self.http.json("GET", "/api/v1/publishes").get("publishes")
        if not isinstance(values, list) or not all(isinstance(v, dict) for v in values):
            raise HereNowError("invalid_response", "Provider did not return a site list.")
        return [{k: value.get(k) for k in ("slug", "siteUrl", "currentVersionId", "displayName")} for value in values]

    def get_site(self, slug: str) -> SiteSnapshot:
        validate_slug(slug)
        return SiteSnapshot.parse(slug, self.http.json("GET", f"/api/v1/publish/{slug}"))

    def bytes_for(self, snapshot: SiteSnapshot, entry: FileEntry) -> bytes:
        if entry.size > self.max_file_bytes:
            raise HereNowError("too_large", "File exceeds the configured read limit.", stage="read_file")
        data = self.http.public_bytes(snapshot.slug, quote(entry.path, safe="/"), max_bytes=self.max_file_bytes)
        if not entry.matches(data):
            raise HereNowError("content_mismatch", "Public bytes differ from the manifest. Re-read later; do not edit this response.", stage="read_file")
        return data

    def read_file(self, slug: str, path: str, base_version_id: str | None = None) -> dict:
        validate_path(path)
        snapshot = self.get_site(slug)
        if base_version_id is not None and snapshot.version != base_version_id:
            raise HereNowError("version_conflict", f"Current version is {snapshot.version}; re-read the site.", stage="read_file")
        entry = snapshot.by_path.get(path)
        if entry is None:
            raise HereNowError("not_found", "File is absent from the current manifest.", stage="read_file")
        result = {"slug": slug, "version": snapshot.version, "file": entry, "content": None}
        if not is_text(entry.content_type):
            return result
        data = self.bytes_for(snapshot, entry)
        if self.get_site(slug).version != snapshot.version:
            raise HereNowError("version_conflict", "Site changed during the file read; read again.", stage="read_file")
        try:
            result["content"] = data.decode("utf-8")
        except UnicodeError as error:
            raise HereNowError("not_utf8", "File is not UTF-8 text.", stage="read_file") from error
        return result
