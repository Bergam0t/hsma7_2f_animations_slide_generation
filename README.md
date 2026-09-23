# HSMA 7 Session 2F: Creating animations and process maps with the vidigi library

Slides: []()

## Setting up the Python environment

The decks execute Python code cells, so Quarto needs a Python environment with Jupyter available. Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`, managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Then render with `uv run quarto render ...` (or plain `quarto render ...` if `.venv` is already active/picked up) -- see below for the exact commands.

## Rendering the decks

This project renders two separate decks, each sharing the same pool of root-level `_SECTION_*.qmd` files (pulled in via `{{< include >}}`) but publishing to its own output directory via a [Quarto project profile](https://quarto.org/docs/projects/profiles.html):

| Deck | Command | Publishes to |
|---|---|---|
| Main deck (`slides.qmd`) | `quarto render --output-dir docs` | `docs/` |
| NHS Open Access showcase (`slides_nhs_oa.qmd`) | `quarto render --profile nhs_oa --output-dir docs_nhs_oa` | `docs_nhs_oa/` |

The default profile's config lives in `_quarto.yml`. The `nhs_oa` profile is `_quarto-nhs_oa.yml`, which overrides `project.render` for that one command -- everything else (format, plugins, filters, the shared `_metadata.yml`) is the same for both decks.

**Always pass `--output-dir` explicitly** -- don't set `project.output-dir` in `_quarto.yml`/`_quarto-nhs_oa.yml`, and don't set a per-document `output-dir` key in a deck's own front matter (Quarto silently ignores the latter for this project type anyway). If `output-dir` is set in the YAML instead, `quarto preview` of a single ad-hoc file not in `project: render:` (e.g. previewing one `_SECTION_*.qmd` on its own -- see below) anchors its web server at that output-dir even though the file's own rendered output still lands next to the source at the project root, and the browser gets a broken 404. This bit us once already -- see the `_docs_cleanup.py` docstring for the full explanation.

`_docs_cleanup.py` (wired in as a `post-render` hook) deletes anything Quarto copies into an output directory that isn't on that profile's `docs-keep` allowlist -- **each profile has its own `docs-keep` list** (in `_quarto.yml` for the default deck, in `_quarto-nhs_oa.yml` for `nhs_oa`), so if a deck starts linking to a new folder at runtime, add it to the matching profile's list, not the other one's. Since `output-dir` isn't in the YAML, the script picks the right list using the `QUARTO_PROFILE` env var Quarto sets for post-render scripts, not the output-dir path.

If you add a third deck, give it its own `_quarto-<name>.yml` profile (render + docs-keep, no output-dir) and always render it with an explicit `--output-dir` too.

### Fast iteration on a single section

Shared format/theme/plugin config lives in `_metadata.yml`, which Quarto merges into every document in the project -- so a single section can be rendered/previewed standalone with the full live-revealjs styling, without duplicating the header and without rebuilding either deck. Both of these work (including the VS Code "Preview" button/CodeLens, which runs the bare form):

```
quarto preview _SECTION_foo.qmd
quarto preview _SECTION_foo.qmd --output-dir _preview
```

The bare form renders next to the source at the project root (gitignored: `_SECTION_*.html`, `_SECTION_*/*`). `--output-dir _preview` (also gitignored) tidies that away into one folder if you'd rather. Either way, never pass `--output-dir docs` or `--output-dir docs_nhs_oa` for a section preview -- those are the real published outputs and the post-render cleanup hook would run against whichever `--output-dir` you point it at.

### Troubleshooting: docs/ (or docs_nhs_oa/) looks broken after a render

Check for a leftover `quarto preview` process before assuming a code bug -- a background watcher racing a direct render call can silently delete files mid-copy. On Windows: `tasklist | findstr /i "quarto deno"`. Elsewhere: `ps aux | grep quarto`. Close it, then render again.

## Useful shortcuts

- Press 'q' to turn the mouse to/from a laser pointer.
- Press 'f' to put the slides into fullscreen
- Press 's' to bring up the speaker view
- Hold 'Alt' and click somewhere on the slide to zoom in. Click again while holding 'Alt' to return to the original zoom level.
