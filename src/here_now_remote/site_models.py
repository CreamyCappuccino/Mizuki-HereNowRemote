"""Manifest values, text changes and validation independent of MCP/HTTP."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class HereNowError(Exception):
    """Safe, actionable error. Never wrap raw HTTP exceptions or secret URLs."""

    def __init__(self, code: str, message: str, *, stage: str = "validation") -> None:
        self.code, self.message, self.stage = code, message, stage
        super().__init__(message)


def validate_slug(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise HereNowError("invalid_slug", "Use a site slug, not a URL.")
    if len(value) > 63:
        raise HereNowError("invalid_slug", "Site slug is longer than a DNS label.")
    return value


def validate_path(value: str, *, writing: bool = False) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise HereNowError("invalid_path", "A nonempty relative file path is required.")
    if any(c in value for c in ("\\", "%", "?", "#", ":")):
        raise HereNowError("invalid_path", "Use a literal relative path without URL syntax.")
    parts = value.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise HereNowError("invalid_path", "Empty, dot and parent path segments are not allowed.")
    if writing and any(
        p.lower() in {".git", ".ssh", "credentials", "id_rsa", "id_ed25519"}
        or p.lower() == ".env" or p.lower().startswith(".env.") for p in parts
    ):
        raise HereNowError("secret_path", "Credential/configuration files must not be published.")
    return value


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def is_text(content_type: str) -> bool:
    mime = content_type.partition(";")[0].strip().lower()
    return mime.startswith("text/") or mime in {
        "application/json", "application/javascript", "application/xml", "image/svg+xml",
    } or mime.endswith(("+json", "+xml"))


def content_type_for(path: str) -> str:
    return {
        ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8", ".json": "application/json",
        ".svg": "image/svg+xml", ".xml": "application/xml", ".txt": "text/plain; charset=utf-8",
    }.get(PurePosixPath(path).suffix.lower(), "text/plain; charset=utf-8")


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    content_type: str
    sha256: str | None = None

    @classmethod
    def parse(cls, value: dict[str, Any]) -> FileEntry:
        path = validate_path(value.get("path"))
        size = value.get("size")
        mime = value.get("contentType", "application/octet-stream")
        sha = value.get("hash")
        if type(size) is not int or size < 0:
            raise HereNowError("invalid_manifest", "Manifest file size is invalid.")
        if not isinstance(mime, str) or not mime or "\r" in mime or "\n" in mime:
            raise HereNowError("invalid_manifest", "Manifest content type is invalid.")
        if sha is not None and (not isinstance(sha, str) or not re.fullmatch("[a-f0-9]{64}", sha)):
            raise HereNowError("invalid_manifest", "Manifest SHA-256 is invalid.")
        return cls(path, size, mime, sha)

    def request_value(self) -> dict[str, Any]:
        value = {"path": self.path, "size": self.size, "contentType": self.content_type}
        if self.sha256 is not None:
            value["hash"] = self.sha256
        return value

    def matches(self, content: bytes) -> bool:
        return len(content) == self.size and (self.sha256 is None or digest(content) == self.sha256)


@dataclass(frozen=True)
class SiteSnapshot:
    slug: str
    version: str
    pending_version: str | None
    files: tuple[FileEntry, ...]

    @property
    def url(self) -> str:
        return f"https://{self.slug}.here.now/"

    @property
    def by_path(self) -> dict[str, FileEntry]:
        return {f.path: f for f in self.files}

    @classmethod
    def parse(cls, slug: str, value: dict[str, Any]) -> SiteSnapshot:
        if value.get("slug") != slug:
            raise HereNowError("invalid_response", "Provider returned a different site.")
        version = value.get("currentVersionId")
        if not isinstance(version, str) or not version:
            raise HereNowError("not_live", "This site has no current published version.")
        manifest = value.get("manifest")
        if not isinstance(manifest, list) or not manifest or not all(isinstance(v, dict) for v in manifest):
            raise HereNowError("invalid_manifest", "Provider returned no complete manifest.")
        files = tuple(FileEntry.parse(item) for item in manifest)
        if len({f.path for f in files}) != len(files):
            raise HereNowError("invalid_manifest", "Duplicate paths in provider manifest.")
        pending = value.get("pendingVersionId")
        if pending is not None and not isinstance(pending, str):
            raise HereNowError("invalid_response", "Invalid pending version.")
        return cls(slug, version, pending, files)


@dataclass(frozen=True)
class TextChange:
    path: str
    content: str
    content_type: str | None = None


def merge_changes(
    snapshot: SiteSnapshot, changes: list[TextChange], *, max_bytes: int,
) -> tuple[dict[str, FileEntry], dict[str, bytes]]:
    if not changes:
        raise HereNowError("empty_changes", "Supply at least one file change.")
    merged, bodies = snapshot.by_path.copy(), {}
    for change in changes:
        path = validate_path(change.path, writing=True)
        if path in bodies:
            raise HereNowError("duplicate_change", "A path appears twice in changes.")
        if not isinstance(change.content, str):
            raise HereNowError("invalid_content", "File contents must be UTF-8 text.")
        try:
            content = change.content.encode("utf-8")
        except UnicodeError as error:
            raise HereNowError("invalid_content", "File contents are not valid UTF-8.") from error
        previous = merged.get(path)
        mime = change.content_type or (previous.content_type if previous else content_type_for(path))
        entry = FileEntry.parse({"path": path, "size": len(content), "contentType": mime, "hash": digest(content)})
        if not is_text(mime):
            raise HereNowError("not_text", "This version accepts text changes only.")
        merged[path], bodies[path] = entry, content
    if sum(map(len, bodies.values())) > max_bytes:
        raise HereNowError("too_large", "Change payload exceeds the configured MCP text limit.")
    return merged, bodies
