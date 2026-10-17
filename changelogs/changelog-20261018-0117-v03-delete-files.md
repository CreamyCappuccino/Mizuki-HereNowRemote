# v0.3 — Targeted Site file deletion

- New MCP tool `delete_site_files(slug, base_version_id, paths)` uses the same Here.now complete-manifest publish pipeline as `update_site_files`, but removes the requested paths while preserving all others. It does not delete the whole Site.
- Existing read+write OAuth scopes and owner-key handling are unchanged. Only explicitly named Site-relative paths can be removed. Missing/duplicate paths, stale snapshots and removing the Site's last file fail before the provider write.
- No separate DB, approval queue, or GitHub synchronization. Official published versions remain available for `restore_version`.
- Added targeted deletion tests, MCP descriptor list and OAuth read-only rejection. Live deletion acceptance is limited to a disposable Site and must be performed only after v0.3 is deployed.
- Existing AIL and Confluence content remain unchanged by this code release. Earlier temporary Confluence page `hnr-demo-20261018.html` was separately removed via an explicitly selected prior version, with 21 original files confirmed.
