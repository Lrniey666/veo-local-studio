# Contributing

Languages: [繁體中文](../CONTRIBUTING.md) · [English](CONTRIBUTING.en.md)

This is a local Windows desktop studio for Veo. Bug fixes, documentation and desktop UX are welcome — match the current code before you start.

## Before you change anything

1. Read the architecture table in [`README.md`](../README.md).
2. Desktop behaviour lives in `app/desktop.py` and `app/services/`. Do not reconstruct the deleted browser UI.
3. Discord behaviour lives in `app/services/discord_bot.py` and [`discord.md`](discord.md). The command is `/veo3`.

When documents disagree with the code, the code wins; then fix the documents.

## Conventions

| Item | Rule |
| --- | --- |
| User-visible strings | Traditional Chinese |
| Public README | Chinese at the repo root; English in `docs/README.en.md` |
| Functions | `snake_case` |
| Classes | `PascalCase` |
| Dates | `YYYY-MM-DD`, Taipei time |

## Please do not

- Commit keys, tokens or machine-absolute paths
- Add `data/`, `outputs/`, `.env` or `*.lnk`
- Bring back the browser UI or a Docker web entry without rewriting the architecture notes
- Put personal wallet jokes in Discord success copy
- Swallow raw Google API errors

Ask before anything irreversible (push, token reset, a paid generation).

## After a change

1. Keep the README and the matching `docs/` guide in step
2. Record notable work under `## [Unreleased]` in `CHANGELOG.md` (Added / Changed / Deprecated / Removed / Fixed / Security)
3. If the desktop layout moved, regenerate the demo shots with `scripts\capture_docs.py` (it uses a throwaway data directory)

Product copy: [`README.md`](../README.md). Packaging: [`packaging.md`](packaging.md).
