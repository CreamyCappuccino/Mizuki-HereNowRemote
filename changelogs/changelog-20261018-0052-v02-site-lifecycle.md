# v0.2 — Site creation, history and explicit restore

- Added `create_site` to publish a new owned personal-account Site from UTF-8 files that include root `index.html`. Uses the existing content validation, canonical provider URL, presigned uploads and finalize/readback; never forwards the provider bearer to R2.
- Added `list_versions` for compact provider-owned version history and `restore_version` for an explicitly chosen prior Site version. Restore checks the last observed current version but does not claim an atomic provider-side restore precondition. The operation affects the whole Site.
- New tools reuse Shared OAuth: version listing requires read scope; creation and restoration require read+write. Existing four tool contracts and Cloudflare routing stay unchanged.
- Added a focused in-memory provider suite and MCP descriptor/permission checks. GitHub Actions [run 39051064122](https://github.com/CreamyCappuccino/Mizuki-HereNowRemote/actions/runs/39051064122): Ruff PASS, 53 pytest PASS with actual MCP SDK installed. Live provider creation/history/restore acceptance and the M4 runtime rollout remain to be done.
- Domain mounts under `nor.strangebasket.com/<path>/` are a separate operations request; no Cloudflare/DNS/DB integration was introduced.
- Existing public release content and account credentials were not changed by these code commits. Public docs remain public-facing; maintainer-only notes are not included.
