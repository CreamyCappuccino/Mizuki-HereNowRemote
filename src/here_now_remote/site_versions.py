"""Read the provider's Site history and explicitly restore an owned version."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .site_models import HereNowError, validate_slug
from .site_reader import SiteReader


@dataclass(frozen=True)
class RestoreReceipt:
    status: str
    slug: str
    restored_from: str
    old_version: str
    current_version: str | None
    message: str = ""


class SiteVersions:
    def __init__(self, reader: SiteReader):
        self.reader = reader
        self.http = reader.http

    def list(self, slug: str) -> tuple[str, list[dict]]:
        validate_slug(slug)
        current = self.reader.get_site(slug).version
        rows = self.http.json("GET", f"/api/v1/publish/{slug}/versions").get("versions")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise HereNowError("invalid_response", "Provider did not return version history.")
        return current, rows

    def restore(self, slug: str, version_id: str, base_version_id: str) -> RestoreReceipt:
        validate_slug(slug)
        if not isinstance(version_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", version_id):
            raise HereNowError("invalid_version", "Choose a version from list_versions.")
        if not isinstance(base_version_id, str) or not base_version_id:
            raise HereNowError("missing_version", "Pass the current version observed before restore.")
        current, rows = self.list(slug)
        if current != base_version_id:
            raise HereNowError("version_conflict", f"Current version is {current}; inspect before restore.")
        known = {r.get("versionId") or r.get("id") for r in rows}
        if version_id not in known:
            raise HereNowError("invalid_version", "Requested version is not in this Site's history.")
        if current == version_id:
            return RestoreReceipt("unchanged", slug, version_id, current, current)
        try:
            restored = self.http.json("POST", f"/api/v1/publish/{slug}/versions/{version_id}/restore")
        except HereNowError:
            # A lost response after POST is not evidence of failure.
            restored = None
        try:
            after = self.reader.get_site(slug)
        except HereNowError:
            return RestoreReceipt("outcome_unknown", slug, version_id, current, None,
                                  "Restore response/current Site unavailable. Inspect before retrying.")
        reported = restored.get("currentVersionId") if restored else None
        if restored is not None and (reported is None or reported == after.version):
            if after.version != current:
                return RestoreReceipt("restored", slug, version_id, current, after.version,
                                      "Provider response and current version checked. Restore affects the whole Site.")
        return RestoreReceipt("outcome_unknown", slug, version_id, current, after.version,
                              "Cannot confirm desired restored content from available metadata; inspect the Site.")
