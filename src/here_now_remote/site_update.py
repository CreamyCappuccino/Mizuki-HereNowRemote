"""Merged-manifest publication with observable outcomes and no private ledger."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace

from .site_models import FileEntry, HereNowError, SiteSnapshot, TextChange, digest, merge_changes
from .site_reader import SiteReader

CONCURRENCY_NOTE = "Uses the provider baseVersionId guard; conflicts are returned without overwrite or blind retry."


@dataclass(frozen=True)
class PublishReceipt:
    status: str
    slug: str
    url: str
    previous_version: str
    target_version: str | None
    current_version: str | None
    changed_paths: tuple[str, ...]
    uploaded: int = 0
    skipped: int = 0
    message: str = ""
    # Only changed-file fingerprints, sufficient to investigate an ambiguous call.
    changed_hashes: dict[str, str] = field(default_factory=dict)


class SiteUpdater:
    def __init__(self, reader: SiteReader, *, max_change_bytes: int = 2 * 1024 * 1024) -> None:
        self.reader = reader
        self.http = reader.http
        self.max_change_bytes = max_change_bytes
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def update(self, slug: str, base_version_id: str, changes: list[TextChange]) -> PublishReceipt:
        if not isinstance(base_version_id, str) or not base_version_id:
            raise HereNowError("missing_version", "Pass the version returned with the files you edited.")
        with self._locks_guard:
            lock = self._locks.setdefault(slug, threading.Lock())
        with lock:
            return self._update(slug, base_version_id, changes)

    def _update(self, slug: str, base: str, changes: list[TextChange]) -> PublishReceipt:
        before = self.reader.get_site(slug)
        self._require_version(before, base)
        merged, bodies = merge_changes(before, changes, max_bytes=self.max_change_bytes)
        # Only hashless legacy entries need bytes. Ordinary unchanged assets stay remote.
        for path, entry in tuple(merged.items()):
            if entry.sha256 is None:
                content = self.reader.bytes_for(before, entry)
                merged[path] = replace(entry, sha256=digest(content))
                bodies[path] = content
        changed = tuple(sorted(c.path for c in changes if merged[c.path] != before.by_path.get(c.path)))
        receipt = PublishReceipt("unchanged", slug, before.url, base, base, base, changed,
                                 changed_hashes={p: merged[p].sha256 for p in changed})
        if not changed:
            return receipt
        self._require_version(self.reader.get_site(slug), base)
        # Provider checks the edited version; preserve existing SPA/TTL/access settings.
        prepared = self.http.json("PUT", f"/api/v1/publish/{slug}",
                                  {"files": [merged[p].request_value() for p in sorted(merged)], "baseVersionId": base})
        upload = prepared.get("upload")
        if not isinstance(upload, dict) or not isinstance(upload.get("versionId"), str) or not upload["versionId"]:
            raise HereNowError("invalid_response", "Prepare did not return a pending version.", stage="prepare")
        version = upload["versionId"]
        receipt = replace(receipt, status="not_published", target_version=version)
        try:
            targets, skipped = self._upload_plan(upload, merged)
            for target in targets:
                path = target["path"]
                body = bodies.get(path)
                if body is None:
                    body = self.reader.bytes_for(before, merged[path])
                self.http.upload(target, body)
            receipt = replace(receipt, uploaded=len(targets), skipped=len(skipped))
            just_before = self.reader.get_site(slug)
            receipt = replace(receipt, current_version=just_before.version)
            self._require_version(just_before, base)
            if just_before.pending_version != version:
                raise HereNowError("version_conflict", "The pending version changed; publication stopped.", stage="pre_finalize")
        except HereNowError as error:
            return replace(receipt, message=f"{error.code} at {error.stage}: {error.message}")

        # Construct the canonical endpoint instead of attaching a key to finalizeUrl.
        finalize_error = None
        finalized = {}
        try:
            finalized = self.http.json("POST", f"/api/v1/publish/{slug}/finalize", {"versionId": version})
        except HereNowError as error:
            finalize_error = error
        # A timeout can occur after publication. Read back; never blindly re-publish.
        try:
            after = self.reader.get_site(slug)
        except HereNowError:
            return replace(receipt, status="outcome_unknown", current_version=None,
                           message="Finalization may have completed. Read the site and compare target version/hashes before retrying.")
        if finalize_error and finalize_error.code == "version_conflict":
            return replace(receipt, status="version_conflict", current_version=after.version,
                           message="Provider rejected a stale base at finalize. Re-read and reconcile before publishing.")
        if finalized.get("unchanged") is True and after.version == finalized.get("currentVersionId") and after.by_path == merged:
            return replace(receipt, status="unchanged", target_version=after.version,
                           current_version=after.version, message="Provider confirmed unchanged content; manifest verified.")
        if after.version == version and after.by_path == merged:
            note = "Publication verified by version and full manifest."
            if finalize_error:
                note += " Recovered by readback after an ambiguous finalize response."
            return replace(receipt, status="published", current_version=after.version, message=note)
        message = "Target version/manifest is not the current publication; inspect before retrying."
        if finalize_error:
            message = f"{finalize_error.code} at finalize. " + message
        return replace(receipt, status="outcome_unknown", current_version=after.version, message=message)

    @staticmethod
    def _require_version(snapshot: SiteSnapshot, base: str) -> None:
        if snapshot.version != base:
            raise HereNowError("version_conflict", f"Current version is {snapshot.version}; re-read and rebase your changes.", stage="version_check")

    @staticmethod
    def _upload_plan(upload: dict, merged: dict[str, FileEntry]) -> tuple[list[dict], list[str]]:
        targets, skipped = upload.get("uploads"), upload.get("skipped", [])
        if not isinstance(targets, list) or not isinstance(skipped, list):
            raise HereNowError("invalid_upload", "Invalid upload plan.", stage="prepare")
        if not all(isinstance(t, dict) and isinstance(t.get("path"), str) for t in targets):
            raise HereNowError("invalid_upload", "Invalid upload target.", stage="prepare")
        if not all(isinstance(p, str) for p in skipped):
            raise HereNowError("invalid_upload", "Invalid skipped-file list.", stage="prepare")
        paths = [t["path"] for t in targets] + skipped
        if len(paths) != len(set(paths)) or set(paths) != set(merged):
            raise HereNowError("invalid_upload", "Upload/skipped paths do not cover the complete manifest.", stage="prepare")
        return targets, skipped
