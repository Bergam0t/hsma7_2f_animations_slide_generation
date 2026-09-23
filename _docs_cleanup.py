"""Post-render cleanup for the Quarto output directory.

WHY THIS EXISTS (please don't delete it as dead weight):

Quarto's default (non-website) project type mirrors the *entire* project
directory into `output-dir` on every render -- not just the rendered deck --
and it does not respect `.gitignore`. Left alone, `docs/` silently fills up
with your source files, `data/` folders, `__pycache__/`, lockfiles, notes,
and multi-megabyte Jupyter intermediates, all of which then get published to
GitHub Pages. In one HSMA deck repo this grew the published folder to 1.4GB.
With multiple decks/profiles (see below), this mirroring can also leak one
deck's own output files into another deck's output-dir -- the allowlist
guards against that too.

Two things that look like fixes but are not:
  * `.quartoignore` only affects `quarto use template` scaffolding. It has
    zero effect on `quarto render`.
  * `project: render:` restricts which files Quarto renders as *documents*,
    but does not stop the wholesale directory copy into `output-dir`.

So this script runs after every render and deletes everything in the output
directory that isn't on an explicit allowlist.

CONFIGURATION LIVES IN `_quarto.yml` (AND `_quarto-<profile>.yml`), NOT HERE:
  * the allowlist comes from the top-level `docs-keep:` list

Edit `docs-keep:` (in the right file) -- not this file -- when a deck gains
a new folder.

MULTIPLE DECKS / PROFILES, AND WHY output-dir ISN'T IN THE YAML:

This project renders more than one deck via Quarto project profiles
(`quarto render --profile <name>`, see `_quarto-<name>.yml`). Each profile
needs its own output-dir (docs/, docs_nhs_oa/, ...) and its own docs-keep
allowlist, so one deck's files don't get kept as if they belonged in
another deck's output-dir.

output-dir is deliberately NOT set in `project:` in either `_quarto.yml` or
a `_quarto-<profile>.yml` -- always pass `--output-dir <dir>` on the render
command line instead (see README.md/notes.md for the exact commands). If
output-dir is set in the YAML, `quarto preview <file>` for a single ad-hoc
file not in `project: render:` (e.g. previewing one `_SECTION_*.qmd` on its
own) anchors its web server at that output-dir, even though the ad-hoc
file's own rendered output still lands next to the source at the project
root -- the browser then gets a broken `/../<file>.html` 404.

Since output-dir is only ever supplied via the command line, this script
can't read it from `_quarto.yml`/`_quarto-<profile>.yml` to pick the right
docs-keep list. Instead it reads the `QUARTO_PROFILE` env var that Quarto
sets for pre/post-render scripts (empty string for the default profile,
e.g. "nhs_oa" when rendered with `--profile nhs_oa`) and uses that profile's
own docs-keep if `_quarto-<profile>.yml` defines one, else falls back to the
base file's list.
"""

import os
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pyyaml missing -- see load_config() for the fallback
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent
QUARTO_YML = PROJECT_ROOT / "_quarto.yml"


def warn(message):
    """Print a warning and exit without deleting anything."""
    print(f"_docs_cleanup.py: {message}")
    print("_docs_cleanup.py: nothing deleted.")
    sys.exit(0)


def parse_simple_list(text, key):
    """Minimal reader for a top-level block of the form:

        key:
          - entry
          - entry

    Used only when pyyaml isn't installed. Deliberately strict -- it returns
    nothing on anything more complicated, which routes us to the warn() path
    rather than to a bad guess about what to delete.
    """
    entries = []
    in_block = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        if not in_block:
            in_block = line.rstrip(":") == key and line.endswith(":")
            continue
        if not line[0].isspace():
            break  # next top-level key -- block is over
        stripped = line.strip()
        if not stripped.startswith("- "):
            return []  # nested/complex structure: refuse to interpret
        entries.append(stripped[2:].strip().strip("'\""))
    return entries


def load_docs_keep(path):
    """Read just the top-level `docs-keep:` list from a config file."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        config = yaml.safe_load(text)
        config = config if isinstance(config, dict) else {}
        return config.get("docs-keep")
    print(
        "_docs_cleanup.py: pyyaml not installed (pip install pyyaml) -- "
        "falling back to simple parsing of docs-keep"
    )
    return parse_simple_list(text, "docs-keep") or None


def active_docs_keep():
    """Pick the docs-keep list for whichever profile is currently rendering.

    Quarto sets QUARTO_PROFILE for pre/post-render scripts: empty for the
    default profile, or the active profile name(s) (comma-separated if more
    than one) otherwise.
    """
    if not QUARTO_YML.is_file():
        warn(f"could not find {QUARTO_YML.name}")
    base_keep = load_docs_keep(QUARTO_YML)

    profile = (os.environ.get("QUARTO_PROFILE") or "").split(",")[0].strip()
    if profile:
        profile_keep = load_docs_keep(PROJECT_ROOT / f"_quarto-{profile}.yml")
        if profile_keep:
            return profile_keep
    return base_keep


def resolve_output_dir():
    """Quarto sets QUARTO_PROJECT_OUTPUT_DIR for pre/post-render scripts --
    that's the ground truth for what actually got rendered this time."""
    output_dir = os.environ.get("QUARTO_PROJECT_OUTPUT_DIR")
    if not output_dir:
        warn("QUARTO_PROJECT_OUTPUT_DIR is not set -- run this via `quarto render`")
    return (PROJECT_ROOT / output_dir).resolve()


def main():
    keep = active_docs_keep()
    if not isinstance(keep, list) or not keep:
        warn(
            "no `docs-keep:` list found for the active profile -- refusing "
            "to guess what is safe to delete"
        )
    keep = set(keep)

    output_dir = resolve_output_dir()

    # Safety rails: never let a misconfigured output-dir turn this into
    # "delete the project".
    if not output_dir.is_dir():
        warn(f"output directory {output_dir} does not exist")
    if output_dir == PROJECT_ROOT or PROJECT_ROOT not in output_dir.parents:
        warn(f"output directory {output_dir} is not inside the project -- aborting")

    label = output_dir.name
    for entry in output_dir.iterdir():
        if entry.name in keep:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        print(f"_docs_cleanup.py: removed stray {label}/{entry.name}")


if __name__ == "__main__":
    main()
