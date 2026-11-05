"""Pre-render: generate the title slide's QR code pointing at the hosted deck.

The title slide shows `assets/slides_qr.svg` when the deck's header sets
`qr-code:` (see title-slide.html). This script (re)writes that file before
every render, from that same header key:

  qr-code: auto   (or `true`) -- work the URL out, so a deck made from this
                  template automatically gets a QR code for its *own* GitHub
                  Pages site:
                    1. a `CNAME` file in docs/ (Pages custom domain), else
                    2. the `origin` git remote, as
                       https://<owner>.github.io/<repo>/ (or
                       https://<owner>.github.io/ for a <owner>.github.io
                       repo). Assumes Pages serves docs/, per README.md.
  qr-code: "https://..."  -- use exactly this URL, e.g. when the hosted copy
                  isn't the repo your clone's `origin` points at.
  (unset/false)   -- no QR code; nothing is written.

The deck is found from the files Quarto is rendering
(QUARTO_PROJECT_INPUT_FILES), falling back to `project: render:` in
_quarto.yml. There is one QR file, so with several decks the first one that
sets `qr-code:` wins.

Never fails the render: if the URL can't be worked out or `segno` isn't
installed, it prints why and leaves any existing QR code alone.
"""

import io
import os
import re
import subprocess
from pathlib import Path

try:
    import yaml
except ImportError:  # pyyaml missing -- see read_qr_setting() for the fallback
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent
QUARTO_YML = PROJECT_ROOT / "_quarto.yml"
QR_FILE = PROJECT_ROOT / "assets" / "slides_qr.svg"

GITHUB_REMOTE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)


def say(message):
    print(f"_make_slides_qr.py: {message}")


def deck_files():
    rendering = os.environ.get("QUARTO_PROJECT_INPUT_FILES", "")
    files = [Path(f) for f in rendering.splitlines() if f.strip()]
    if not files and yaml is not None and QUARTO_YML.is_file():
        config = yaml.safe_load(QUARTO_YML.read_text(encoding="utf-8")) or {}
        files = [Path(f) for f in (config.get("project") or {}).get("render", [])]
    files = [f if f.is_absolute() else PROJECT_ROOT / f for f in files]
    return [f for f in files if f.suffix == ".qmd" and f.is_file()]


def read_qr_setting(deck):
    """The deck header's `qr-code:` value, or None if it isn't set."""
    text = deck.read_text(encoding="utf-8")
    header = re.match(r"---\s*\n(.*?)\n---\s*(\n|$)", text, re.DOTALL)
    if not header:
        return None
    if yaml is not None:
        return (yaml.safe_load(header[1]) or {}).get("qr-code")
    # No pyyaml: just read a top-level `qr-code: value` line
    line = re.search(r"""^qr-code:\s*["']?([^"'#\n]*?)["']?\s*(#.*)?$""",
                     header[1], re.MULTILINE)
    return line[1] if line else None


def url_from_cname():
    cname = PROJECT_ROOT / "docs" / "CNAME"
    if cname.is_file():
        domain = cname.read_text(encoding="utf-8").strip()
        if domain:
            return f"https://{domain}/"
    return None


def url_from_git_remote():
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    match = GITHUB_REMOTE.search(remote)
    if not match:
        say(f"origin remote isn't a GitHub URL ({remote!r})")
        return None
    owner, repo = match["owner"].lower(), match["repo"]
    if repo.lower() == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def main():
    # str() so YAML booleans and the no-pyyaml fallback's strings agree
    value = ""
    for deck in deck_files():
        value = str(read_qr_setting(deck) or "").strip()
        if value.lower() not in ("", "false"):
            break
    if value.lower() in ("", "false"):
        return

    if value.lower() in ("auto", "true"):
        url = url_from_cname() or url_from_git_remote()
        if not url:
            say("couldn't work out the hosted URL -- give it as "
                "`qr-code: \"https://...\"` in the deck header. "
                "QR code left unchanged.")
            return
    elif re.match(r"https?://", value):
        url = value
    else:
        say(f"`qr-code: {value}` should be `auto` or a URL -- "
            "QR code left unchanged.")
        return

    try:
        import segno
    except ImportError:
        say("segno not installed (uv sync / pip install segno) -- "
            "QR code left unchanged.")
        return

    # A standalone file (SVG namespace, viewBox not fixed size) so it works
    # in an <img> and scales to whatever size the CSS gives it
    buffer = io.BytesIO()
    segno.make(url, error="m", micro=False).save(
        buffer, kind="svg", dark="#000", light="#fff", border=4, scale=10,
        xmldecl=False, svgclass=None, lineclass=None, omitsize=True,
    )
    svg = buffer.getvalue().decode("utf-8")
    if QR_FILE.is_file() and QR_FILE.read_text(encoding="utf-8") == svg:
        return
    QR_FILE.parent.mkdir(exist_ok=True)
    QR_FILE.write_text(svg, encoding="utf-8")
    say(f"wrote {QR_FILE.relative_to(PROJECT_ROOT).as_posix()} -> {url}")


if __name__ == "__main__":
    main()
