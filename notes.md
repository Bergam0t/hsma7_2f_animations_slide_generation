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
