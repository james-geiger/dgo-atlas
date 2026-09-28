"""Check that every internal link in the built site resolves to a real file.

`dgo-atlas build` runs this after rendering; `dgo-atlas linkcheck [SITE]` runs it
on its own.

Every page computes its own relative path back to the site root so that the
site works both under a GitHub Pages project subpath and from file:// when a
steward opens the PR-preview artifact out of the downloaded zip. That scheme
is easy to get subtly wrong -- one page at the wrong depth and a whole
section 404s -- and a broken link on a governance site costs trust. So CI
checks it.

External links are not fetched; this only verifies the site is internally
consistent.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urldefrag

LINK = re.compile(r'(?:href|src)="([^"]+)"', re.IGNORECASE)

# "#" is deliberately absent: a same-page anchor still has to point at an id
# that exists, and that check happens below.
SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "//")


def check(root: Path, base_path: str = "/") -> list[str]:
    problems: list[str] = []
    pages = sorted(root.rglob("*.html"))
    if not pages:
        return [f"{root}: no HTML pages found"]

    for page in pages:
        html = page.read_text(encoding="utf-8")
        anchors = {m.group(1) for m in re.finditer(r'id="([^"]+)"', html)}

        for raw in LINK.findall(html):
            if raw.startswith(SKIP_PREFIXES) or not raw.strip():
                continue

            target, fragment = urldefrag(raw)
            # Static assets carry a ?v=<digest> cache buster; the file on disk
            # is the part before the query.
            target = target.split("?", 1)[0]
            if not target:
                # Same-page anchor.
                if fragment and fragment not in anchors:
                    problems.append(
                        f"{page.relative_to(root)}: #{fragment} does not exist on this page"
                    )
                continue

            # 404.html uses root-absolute paths because it is served in
            # response to any URL, at any depth. Those resolve against the site
            # root, not the page's directory.
            path = unquote(target)
            if path.startswith(base_path) and base_path != "/":
                path = "/" + path[len(base_path):]
            base = root if path.startswith("/") else page.parent
            resolved = (base / path.lstrip("/")).resolve()
            if not resolved.exists():
                problems.append(
                    f"{page.relative_to(root)}: {raw} -> missing {_display(resolved, root)}"
                )
                continue

            # Guard against a relative path climbing out of the site.
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                problems.append(
                    f"{page.relative_to(root)}: {raw} escapes the site root"
                )

    return problems


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)

