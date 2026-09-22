Add a 'what about warm-up' fairly early on, to say we prefer to record everything in vidigi and filter later

Change to use replication_id everywhere (even before it's introduced in the beginner model)

## Fast iteration on a single section

Shared format/theme/plugin config lives in `_metadata.yml`, which Quarto
merges into every document in the project -- so a single section can be
rendered/previewed standalone with the full live-revealjs styling, without
duplicating the header and without rebuilding the whole deck:

```
quarto preview _SECTION_foo.qmd --output-dir _preview
```

Always pass `--output-dir _preview` (gitignored) for these -- never let a
section preview write into `docs/`, since that's the real published output
and post-render cleanup hooks run against whatever `--output-dir` points at.

## Rendering the two decks

`slides.qmd` (the default profile) and `slides_nhs_oa.qmd` (the `nhs_oa`
profile) publish to separate output dirs, since a per-document `output-dir`
key doesn't actually work for this project type (Quarto silently ignores
it -- `docs/` going stale after the section-restructuring was this bug).
Project profiles handle it instead:

```
quarto render                    # slides.qmd       -> docs/
quarto render --profile nhs_oa   # slides_nhs_oa.qmd -> docs_nhs_oa/
```

See `_quarto-nhs_oa.yml` for the profile override.
