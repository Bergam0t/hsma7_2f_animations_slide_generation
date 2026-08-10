"""Post-render cleanup for the Quarto output directory.

WHY THIS EXISTS (please don't delete it as dead weight):

Quarto's default (non-website) project type mirrors the *entire* project
directory into `output-dir` on every render -- not just the rendered deck --
and it does not respect `.gitignore`. Left alone, `docs/` silently fills up
with your source files, `data/` folders, `__pycache__/`, lockfiles, notes,
and multi-megabyte Jupyter intermediates, all of which then get published to
GitHub Pages. In one HSMA deck repo this grew the published folder to 1.4GB.

Two things that look like fixes but are not:
  * `.quartoignore` only affects `quarto use template` scaffolding. It has
    zero effect on `quarto render`.
  * `project: render:` restricts which files Quarto renders as *documents*,
    but does not stop the wholesale directory copy into `output-dir`.

So this script runs after every render and deletes everything in the output
directory that isn't on an explicit allowlist.

CONFIGURATION LIVES IN `_quarto.yml`, NOT IN HERE:
  * the output directory comes from `project: output-dir:`
  * the allowlist comes from the top-level `docs-keep:` list

Edit that list -- not this file -- when your deck gains a new folder.
"""

import os
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pyyaml missing -- see read_keep_list() for the fallback
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent
QUARTO_YML = PROJECT_ROOT / "_quarto.yml"


def warn(message):
    """Print a warning and exit without deleting anything."""
    print(f"_docs_cleanup.py: {message}")
    print("_docs_cleanup.py: nothing deleted.")
    sys.exit(0)


def read_yaml_text():
    if not QUARTO_YML.is_file():
        warn(f"could not find {QUARTO_YML.name}")
    return QUARTO_YML.read_text(encoding="utf-8")


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


def read_keep_list(text):
    if yaml is not None:
        config = yaml.safe_load(text)
        config = config if isinstance(config, dict) else {}
        return config.get("docs-keep")
    print(
        "_docs_cleanup.py: pyyaml not installed (pip install pyyaml) -- "
        "falling back to simple parsing of docs-keep"
    )
    return parse_simple_list(text, "docs-keep")


def parse_simple_scalar(text, key):
    """Fallback reader for a `key: value` line, used when pyyaml is absent."""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip().strip("'\"")
    return None


def read_output_dir(text):
    """Quarto sets QUARTO_PROJECT_OUTPUT_DIR for pre/post-render scripts.
    Fall back to _quarto.yml, then to the Quarto default of 'docs'."""
    output_dir = os.environ.get("QUARTO_PROJECT_OUTPUT_DIR")
    if not output_dir:
        if yaml is not None:
            config = yaml.safe_load(text)
            if isinstance(config, dict):
                output_dir = (config.get("project") or {}).get("output-dir")
        else:
            output_dir = parse_simple_scalar(text, "output-dir")
    return (PROJECT_ROOT / (output_dir or "docs")).resolve()


def main():
    text = read_yaml_text()

    keep = read_keep_list(text)
    if not isinstance(keep, list) or not keep:
        warn(
            "no `docs-keep:` list found in _quarto.yml -- refusing to guess "
            "what is safe to delete"
        )
    keep = set(keep)

    output_dir = read_output_dir(text)

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
