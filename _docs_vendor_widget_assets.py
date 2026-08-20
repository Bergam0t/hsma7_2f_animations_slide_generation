"""Post-render fixup: point Quarto's ipywidgets script tags at vendored copies.

WHY THIS EXISTS (please don't delete it as dead weight):

`sections/_vidigi_process_maps.qmd` displays a live `ipycytoscape` widget
(via vidigi's `dfg_to_cytoscape`). Quarto embeds this the standard ipywidgets
way, which means the rendered `index.html` contains a `<script>` tag that
loads RequireJS from a CDN, and a second `<script>` tag that loads
`@jupyter-widgets/html-manager`'s `embed-amd.js` (also from a CDN, pinned to
`@*` i.e. "whatever is latest right now"). At view time, `embed-amd.js` then
tries to fetch the actual widget module (`jupyter-cytoscape`) from a CDN too.

That's three CDN round-trips required just to see the slide, every time it's
viewed. If the machine has no/blocked internet access to jsdelivr/unpkg --
locked-down laptop, teaching venue wifi, corporate proxy, ad-blocker -- the
widget silently never renders (confirmed by testing with those hosts
blocked: it stays an inert `<script type="application/vnd.jupyter.widget-view+json">`
tag, nothing more).

This script rewrites those two auto-injected `<script src="https://...">`
tags in the rendered `docs/index.html` to point at local vendored copies
(committed under `resources/vendor/`, already copied into
`docs/resources/vendor/` by Quarto's own directory copy since `resources` is
on the `docs-keep` allowlist), and pre-registers a RequireJS path for
`jupyter-cytoscape` pointing at its vendored copy too, so `embed-amd.js`
never needs to fall back to a CDN URL for it. See
`@jupyter-widgets/html-manager`'s `embed-amd.js`: it always tries
`require(["jupyter-cytoscape"])` first and only computes a CDN URL if that
fails -- pre-registering the path is the supported way to short-circuit it,
not a timing hack.

If you bump the vendored `@jupyter-widgets/html-manager` or `jupyter-cytoscape`
versions, just re-download the files in `resources/vendor/` -- this script
doesn't hardcode version numbers, only CDN host/package prefixes.
"""

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

REQUIREJS_SCRIPT_RE = re.compile(
    r'<script[^>]*\ssrc="https://cdn\.jsdelivr\.net/npm/requirejs@[^"]*"[^>]*></script>'
)
HTML_MANAGER_SCRIPT_RE = re.compile(
    r'<script[^>]*\ssrc="https://cdn\.jsdelivr\.net/npm/@jupyter-widgets/html-manager@[^"]*"[^>]*></script>'
)

REQUIREJS_LOCAL = '<script src="resources/vendor/requirejs/require.min.js"></script>'
HTML_MANAGER_LOCAL = (
    '<script src="resources/vendor/jupyter-widgets-html-manager/embed-amd.js"></script>'
)
CYTOSCAPE_PATH_CONFIG = (
    "<script>requirejs.config({paths: "
    '{"jupyter-cytoscape": "resources/vendor/jupyter-cytoscape/index"}});</script>'
)


def warn(message):
    print(f"_docs_vendor_widget_assets.py: {message}")


def read_output_dir():
    output_dir = os.environ.get("QUARTO_PROJECT_OUTPUT_DIR")
    return (PROJECT_ROOT / (output_dir or "docs")).resolve()


def main():
    output_dir = read_output_dir()
    index_html = output_dir / "index.html"
    if not index_html.is_file():
        warn(f"could not find {index_html} -- nothing to do")
        return

    text = index_html.read_text(encoding="utf-8")

    if not REQUIREJS_SCRIPT_RE.search(text) or not HTML_MANAGER_SCRIPT_RE.search(text):
        warn(
            "no ipywidgets CDN <script> tags found in index.html "
            "(deck may not use any ipywidgets output) -- leaving file untouched"
        )
        return

    text = REQUIREJS_SCRIPT_RE.sub(REQUIREJS_LOCAL, text, count=1)
    text = HTML_MANAGER_SCRIPT_RE.sub(
        CYTOSCAPE_PATH_CONFIG + HTML_MANAGER_LOCAL, text, count=1
    )

    index_html.write_text(text, encoding="utf-8")
    print(
        "_docs_vendor_widget_assets.py: pointed ipywidgets script tags at "
        "resources/vendor/ (no CDN calls needed to render the interactive "
        "process map)"
    )


if __name__ == "__main__":
    main()
