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
  * the output directory comes from `project: output-dir:`
  * the allowlist comes from the top-level `docs-keep:` list

If this project renders more than one deck via project profiles
(`quarto render --profile <name>`, see `_quarto-<name>.yml`), each profile
file can declare its own `project: output-dir:` and its own `docs-keep:` --
this script picks whichever one matches the output directory actually in use
for the current render, so one deck's files don't get kept as if they
belonged in another deck's output-dir. A profile file that only overrides
`output-dir` and not `docs-keep` inherits the base file's list.

Edit `docs-keep:` (in the right file) -- not this file -- when a deck gains
a new folder.
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


def parse_simple_scalar(text, key):
    """Fallback reader for a `key: value` line, used when pyyaml is absent."""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip().strip("'\"")
    return None


def load_config(path):
    """Read a _quarto.yml / _quarto-<profile>.yml into
    {"docs-keep": [...] | None, "output-dir": str | None}."""
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        config = yaml.safe_load(text)
        config = config if isinstance(config, dict) else {}
        return {
            "docs-keep": config.get("docs-keep"),
            "output-dir": (config.get("project") or {}).get("output-dir"),
        }
    print(
        "_docs_cleanup.py: pyyaml not installed (pip install pyyaml) -- "
        "falling back to simple parsing"
    )
    return {
        "docs-keep": parse_simple_list(text, "docs-keep") or None,
        "output-dir": parse_simple_scalar(text, "output-dir"),
    }


def load_candidates():
    """One entry per known project config (base + each profile override),
    as (output-dir-relative-path, docs-keep-list)."""
    if not QUARTO_YML.is_file():
        warn(f"could not find {QUARTO_YML.name}")

    base = load_config(QUARTO_YML)
    candidates = [(base["output-dir"] or "docs", base["docs-keep"])]

    for profile_path in sorted(PROJECT_ROOT.glob("_quarto-*.yml")):
        profile = load_config(profile_path)
        if not profile["output-dir"]:
            continue  # doesn't change output-dir -- nothing extra to match
        candidates.append((profile["output-dir"], profile["docs-keep"] or base["docs-keep"]))

    return candidates


def resolve_output_dir(default_relative):
    """Quarto sets QUARTO_PROJECT_OUTPUT_DIR for pre/post-render scripts --
    that's the ground truth for what actually got rendered this time."""
    output_dir = os.environ.get("QUARTO_PROJECT_OUTPUT_DIR")
    return (PROJECT_ROOT / (output_dir or default_relative)).resolve()


def main():
    candidates = load_candidates()
    output_dir = resolve_output_dir(candidates[0][0])

    keep = None
    for relative, candidate_keep in candidates:
        if (PROJECT_ROOT / relative).resolve() == output_dir:
            keep = candidate_keep
            break
    else:
        # No config declares this output-dir (e.g. a one-off --output-dir on
        # the command line) -- fall back to the base allowlist.
        keep = candidates[0][1]

    if not isinstance(keep, list) or not keep:
        warn(
            "no matching `docs-keep:` list found for this output-dir -- "
            "refusing to guess what is safe to delete"
        )
    keep = set(keep)

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
