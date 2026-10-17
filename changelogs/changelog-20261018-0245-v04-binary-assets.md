# HNR v0.4 — opt-in binary assets (2026-10-18)

- Added optional `encoding: "utf-8" | "base64"` to each `ChangeInput` for both `create_site` and `update_site_files`. Default remains UTF-8; existing calls need no changes.
- Binary bytes are canonical padded base64-decoded, size-checked (2 MiB decoded total), SHA-256 hashed, MIME inferred for common image/media extensions or accepted explicitly; provider gets the original bytes, never the textual base64 string. The existing full-manifest/prepare/PUT/finalize/readback and `baseVersionId` conflict handling remain unchanged.
- `read_site_file` now has optional `binary_mode: "metadata" | "base64"` (default metadata). Binary files show MIME/size/hash normally; opt-in base64 reads are capped at 256 KiB and hash verified. Text reads remain UTF-8.
- Added fake-provider image upload/readback tests, create-with-image coverage, malformed base64/size validation, and actual MCP SDK tool-schema checks. Existing site update/delete/versions/restoration paths remain unchanged.
- No DB, new scopes, Cloudflare changes, or GitHub automatic sync. Live provider binary acceptance and M1 rollout are pending; test only on the retained independent `robust-pepper-v8fd` site, not AIL/Confluence.
