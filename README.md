# Mizuki-HereNowRemote

A lightweight Remote MCP for reading and updating files in owned [here.now](https://here.now) sites without changing their existing URLs.

**Status:** design draft; MCP implementation and deployment have not started.

## Design and handoff

- [Design: phases, decisions, open questions, and source map](docs/DESIGN.md)
- [Design change log](changelogs/changelog-20261017-1615-initial-design.md)

Core workflow: list sites → read a versioned file → edit HTML/CSS/JS → publish a full merged manifest with only changed bytes uploaded → verify the live result.

The MCP does not replace a CMS or implement editorial approvals, databases, queues, or page-preview tooling.
