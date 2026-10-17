# Mizuki-HereNowRemote

A small MCP for reading and editing HTML/CSS/JS in owned [here.now](https://here.now) sites without changing their URLs.

**Status:** v0.1 implemented; [CI passed](https://github.com/CreamyCappuccino/Mizuki-HereNowRemote/actions/runs/39018635047) with 49 tests including the actual MCP SDK, plus Ruff. Provider operations use an in-memory HTTP test service. Live here.now publishing and operator-host deployment remain unverified.

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

## Four tools

| Tool | Purpose |
| --- | --- |
| `list_sites()` | Personal-account site list |
| `get_site(slug)` | Current version and complete manifest |
| `read_site_file(slug, path, base_version_id?)` | Read owner-authenticated UTF-8 text and verify its manifest hash |
| `update_site_files(slug, base_version_id, changes)` | Replace/add requested text files; keep all other files |

`changes` is a list of `{ "path": "assets/style.css", "content": "..." }`. An optional `content_type` changes the MIME type; omitting it preserves the existing type. The `base_version_id` must come from the files that were actually edited, not from a fresh read immediately before writing.

Publication is one tool call: merge manifest → upload required bytes → finalize → compare current version/manifest. Output is compact text with a matching minimal `structuredContent.result` string and `outputSchema` on all four tools; errors remain MCP error results. No new CMS, database, approval queue or Git sync.

Remote HTTP has a side-effect-free, unauthenticated `GET /health` returning `{"status":"ok"}` for origin and tunnel liveness checks. It does not contact here.now or expose site/credential data.

## Boundaries that matter

- File reads use the **owner-authenticated API**, not public URLs or visitor passwords. The current official Skill documents support for password/restricted sites. Binary reads return metadata; live account acceptance is still pending.
- API credentials are used only on `https://here.now`. Owner file downloads use that same API; signed R2 uploads never receive them. Redirects are not followed.
- Changed files are UTF-8 text, up to 2 MiB total. File reads are bounded to 1 MiB per file. These limits bound MCP payload/memory size, not HTML capabilities; intentional JavaScript is not sanitized away.
- The complete existing manifest is retained. No file deletion, SPA/access/TTL setting changes, automatic rollback or blind write retry.
- The edited version is sent as **`baseVersionId`**. The current official publisher documents stale-base rejection, including at finalize. Detected conflicts are returned without automatic overwrite. Process-local serialization and version readbacks supplement, not replace, the provider check.
- A failed response is not proof of a failed publish. Receipts report `outcome_unknown` when readback cannot settle it, with the target version and changed-file hashes.

## Documents

- [Design and phase/source index](docs/DESIGN.md)
- [Setup, API evidence and test scope](docs/IMPLEMENTATION.md)
- [Change log](changelogs/)