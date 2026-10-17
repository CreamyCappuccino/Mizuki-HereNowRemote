# Mizuki-HereNowRemote

A small MCP for reading and editing text and binary files in owned [here.now](https://here.now) sites without changing their URLs.

**Status:** v0.4 source supports optional base64 image/binary assets in create/update and opt-in binary reads. The earlier v0.3 eight-tool service is deployed. New binary paths are CI-tested and await the operator rollout and a live upload/readback smoke.

## Use

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[mcp,dev]'
python -m pytest -q
herenow-remote --transport stdio
```

Set `HERENOW_API_KEY` in the process environment, or use the existing owner-only `~/.herenow/credentials` file (0600). Never put the key in chat, committed files, a command-line argument, or site JavaScript.

The MCP SDK is an optional dependency so the provider core can be tested independently. The MCP host targets **SDK 2.0.0**, not the v1 FastMCP interface.

## Eight tools

| Tool | Purpose |
| --- | --- |
| `list_sites()` | Personal-account site list |
| `get_site(slug)` | Current version and complete manifest |
| `read_site_file(slug, path, base_version_id?, binary_mode?)` | Read UTF-8 or return binary metadata; optionally return small binary files as base64 |
| `update_site_files(slug, base_version_id, changes)` | Replace/add requested UTF-8 or base64 files; keep all other files |
| `delete_site_files(slug, base_version_id, paths)` | Remove only named Site files; preserve all remaining files and versions |
| `create_site(files, display_name?)` | Create a new public personal-account site from UTF-8 and/or base64 files (root index.html required) and return its URL |
| `list_versions(slug)` | List historical published versions of an owned site |
| `restore_version(slug, version_id, base_version_id)` | Explicitly restore the entire site to a selected saved version |

`changes`/`files` accept `{ "path": "assets/style.css", "content": "..." }` as before. Optional `encoding` defaults to `"utf-8"`; set `"base64"` to upload images or other binary bytes. For example `{ "path": "assets/logo.png", "content": "<canonical base64>", "encoding": "base64" }`. Optional `content_type` preserves existing MIME or infers common formats from the extension (PNG, JPEG, WebP, GIF, AVIF, PDF, fonts). Unknown extensions can specify MIME explicitly. The `base_version_id` must come from the files that were actually edited, not from a fresh read immediately before writing.

Publication is one tool call: merge manifest → upload required bytes → finalize → compare current version/manifest. Output is compact text with a matching minimal `structuredContent.result` string and `outputSchema` on all eight tools; errors remain MCP error results. No new CMS, database, approval queue or Git sync.

Remote HTTP has a side-effect-free, unauthenticated `GET /health` returning `{"status":"ok"}` for origin and tunnel liveness checks. It does not contact here.now or expose site/credential data.

Custom `nor.strangebasket.com/<path>/` mounts remain separate Cloudflare operations requests; this MCP never creates DNS or Tunnel routes.

## Boundaries that matter

- File reads use the **owner-authenticated API**, not public URLs or visitor passwords. Binary reads default to size/MIME/SHA metadata only. Set `binary_mode="base64"` to return binary bytes up to 256 KiB as base64 (manifest hash verified). Larger files can still be identified by their metadata.
- API credentials are used only on `https://here.now`. Owner file downloads use that same API; signed R2 uploads never receive them. Redirects are not followed.
- Changed files are UTF-8 text or validated canonical base64 decoded to bytes, up to 2 MiB total decoded payload. File reads are bounded to 1 MiB per file and binary-to-base64 responses to 256 KiB. Huge image assets should use a different transfer route if needed. These limits bound MCP payload/memory size; intentional JavaScript is not sanitized away.
- Updates preserve all unmodified files. Targeted deletion removes only explicitly named paths from the next complete manifest, rejecting unknown paths and requests that would leave a Site empty. Versions remain available for restoration. There is no whole-Site deletion tool, SPA/access/TTL change, automatic rollback or blind write retry.
- The edited version is sent as **`baseVersionId`**. The current official publisher documents stale-base rejection, including at finalize. Detected conflicts are returned without automatic overwrite. Process-local serialization and version readbacks supplement, not replace, the provider check.
- A failed response is not proof of a failed publish. Receipts report `outcome_unknown` when readback cannot settle it, with the target version and changed-file hashes.

## Documents

- [Official here.now API documentation](https://here.now/docs)
- [Official here.now publisher](https://github.com/heredotnow/skill/tree/main/here-now)
- [Change log](changelogs/)

Maintainer-only notes are not part of this public repository. The package is
independently buildable from its public dependencies; no private documentation
or private package is required.