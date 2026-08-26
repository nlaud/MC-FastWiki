# MC-FastWiki

A fast, keyboard-driven Minecraft **Java Edition** reference, built for draftout matches. You type
a name, you press Enter, and the answer appears. The site builds to static files. The browser
never calls a wiki and never calls a game server.

The repository holds two halves. The **pipeline** is Python. It runs at build time, it reads
upstream data, and it writes JSON into `/data/dist`. The **web app** is TypeScript. It reads that
committed JSON and nothing else. The two halves never import from each other. They meet at the
JSON Schema in `/pipeline/schema`.

## Requirements

- **Python 3.12 or later** — the pipeline. `pyproject.toml` sets this bound.
- **Node 22.13 or later** — the web app and the build scripts. `package.json` sets this bound.
- **pnpm 11.23.0** — the package manager. `package.json` pins this version, and `corepack enable`
  installs the pinned one for you.

A pytest gate reads the three versions above and compares each one against its manifest. The gate
fails when the README and a manifest disagree.

## No JDK, no jars

**Building this project needs no Java.** Do not install a JDK. Do not download a game jar.

Two senses of the word meet here, so keep them apart. _Java Edition_ is the edition of the game
this reference covers, and covering it alone is the first rule of `CLAUDE.md`. The Java _language_
is a build dependency that this repository does not have.

Every other Minecraft data project runs Mojang's data generator, and that generator needs a JVM.
So a new contributor installs a JDK before anybody says otherwise. This project does not run the
generator. `misode/mcmeta` runs it for each version and publishes the output as plain JSON on
GitHub. The pipeline fetches that JSON. Nothing here starts a JVM, and nothing here reads a jar.

One thing this rule depends on: mcmeta must stay current. It has published within hours of each
release so far. If it ever lags a release, the fallback is to run Mojang's generator by hand and
feed the output in. `docs/mcmeta-fallback.md` holds that procedure. It is an escape hatch for one
person on one machine, not a step of the build, and nothing in this repository runs it.

## Quick start

Install the tools of the half you work on. The web app never invokes the pipeline, so you do not
need both.

### Web app

1. Install the Node dependencies. Run `pnpm install`.
2. Start the dev server. Run `pnpm dev`.
3. Build the static site from the committed data. Run `pnpm build`.

### Pipeline

1. Install the Python dependencies. Run `uv sync`.
2. Ask whether a new Minecraft release needs a rebuild. Run `python -m pipeline check`.
3. Run the full pipeline. Run `python -m pipeline build`. This step uses the network.
4. Re-check existing output against the schema. Run `python -m pipeline validate`.

## Gates

Run these before you commit:

| Command | What it checks |
| --- | --- |
| `pnpm test` | The web tests. It fails first when `/web/types` is stale. |
| `pnpm lint` | ESLint over the web app, the build config, and the build scripts. |
| `pnpm format:check` | Prettier. `pnpm format` writes the fixes. |
| `pnpm typecheck` | The web types. Neither `pnpm test` nor `pnpm lint` reports a type error. |
| `pytest` | The pipeline tests and the repository invariants. |
| `ruff check .` | The pipeline lint. |
| `mypy` | The pipeline types, in strict mode. |

## Where to read next

- `CLAUDE.md` and `AGENTS.md` — the architecture, the data sources, and the rules of this
  repository. The two files are mirrors, and they must stay byte-identical below the horizontal
  rule.
- `TODO.md` — the build plan, ordered by dependency, with the resolved decisions at the bottom.
- `docs/mcmeta-fallback.md` — what one person does by hand if upstream mcmeta ever lags a
  Minecraft release. Read it only when a build reports a 404 on an mcmeta tag.

Every entry above names a file that a fresh clone holds, and a pytest gate keeps it that way.

## License and attribution

This project is free and non-commercial, and it stays that way.

Minecraft Wiki content is CC BY-NC-SA 3.0 and needs attribution. Every entity keeps a `wikiUrl`,
and the interface shows a visible credit. Game textures and fonts stay the property of Mojang.
Mojang's brand guidelines let a non-commercial fan project use the game assets. This is such a
project.

MC-FastWiki is not an official Minecraft product. Mojang and Microsoft do not approve it and are
not associated with it.
