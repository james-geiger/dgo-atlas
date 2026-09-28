"""Authored Markdown pages: the landing page, guides, and standards.

Not everything on the site comes from governance data. The narrative -- how
a term becomes official, who to ask, local standards -- is prose, and prose
belongs in Markdown rather than in a schema.

Each file in the content directory carries YAML front matter and renders through the
same templates as the generated pages, so an authored page and a term page
look like they belong to the same site.

Front matter keys:
  title      (required) page heading
  eyebrow    small uppercase label above the heading
  lede       serif standfirst paragraph
  nav_group  which sidebar group to file it under
  nav_label  sidebar text, defaults to title
  order      sort order within the group
  meta       list of "Reviewed 12 Aug 2026"-style facts under the heading
  badge      status badge shown next to the eyebrow
  toc        true to build an on-this-page rail from the h2s
  hub        true to mark this the site landing page
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from markdown_it import MarkdownIt

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class ContentError(Exception):
    """Raised when an authored page is malformed."""


@dataclass
class ContentPage:
    path: str
    title: str
    html: str
    eyebrow: str | None = None
    lede: str | None = None
    nav_group: str | None = None
    nav_label: str | None = None
    order: int = 100
    meta: list[str] = field(default_factory=list)
    badge: str | None = None
    toc: list[dict] = field(default_factory=list)
    is_hub: bool = False
    summary: str = ""

    @property
    def url(self) -> str:
        return self.path


def _markdown() -> MarkdownIt:
    # "commonmark" plus tables, which the classification standard needs.
    return MarkdownIt("commonmark", {"typographer": True}).enable(["table", "strikethrough"])


def _headings(html: str) -> tuple[list[dict], str]:
    """Pull h2s out of rendered HTML and give each one an id for the TOC rail.

    Returns the TOC entries and the HTML with ids added to the headings.
    """
    entries: list[dict] = []

    def add_id(match: re.Match) -> str:
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or f"s{len(entries)}"
        entries.append({"id": slug, "label": text})
        return f'<h2 id="{slug}"{match.group(1)}>{match.group(2)}</h2>'

    html = re.sub(r"<h2([^>]*)>(.*?)</h2>", add_id, html, flags=re.DOTALL)
    return entries, html


def _callouts(html: str) -> str:
    """Turn blockquotes opening with **Required** / **Good to know** / **In review**
    into the design's styled callouts, so authors do not write HTML by hand."""
    kinds = {
        "required": "required",
        "good to know": "good_to_know",
        "in review": "in_review",
        "draft": "draft",
    }

    def replace(match: re.Match) -> str:
        body = match.group(1)
        label_match = re.match(
            r"\s*<p>\s*<strong>([^<]+)</strong>\s*(?:<br\s*/?>)?\s*", body
        )
        if not label_match:
            return match.group(0)
        label = label_match.group(1).strip()
        kind = kinds.get(label.lower())
        if kind is None:
            return match.group(0)
        rest = body[label_match.end() :]
        if not rest.lstrip().startswith("<p>"):
            rest = "<p>" + rest
        return (
            f'<div class="callout callout--{kind}">'
            f'<div class="callout__label">{label}</div>{rest}</div>'
        )

    return re.sub(r"<blockquote>(.*?)</blockquote>", replace, html, flags=re.DOTALL)


def load(content_root: Path) -> list[ContentPage]:
    """Load every .md under content_root, deepest paths last."""
    if not content_root.exists():
        return []

    md = _markdown()
    pages: list[ContentPage] = []

    for source in sorted(content_root.rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(text)
        if not match:
            raise ContentError(
                f"{source}: no YAML front matter. Every content page needs at "
                "least a `title:` between --- fences at the top."
            )
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ContentError(f"{source}: front matter is not valid YAML: {exc}") from exc
        if "title" not in meta:
            raise ContentError(f"{source}: front matter has no `title`.")

        body = text[match.end() :]
        html = md.render(body)
        headings, html = _headings(html)
        html = _callouts(html)

        rel = source.relative_to(content_root).with_suffix(".html")
        out_path = "index.html" if meta.get("hub") else str(rel).replace("\\", "/")

        # First paragraph of prose, for the search index.
        plain = re.sub(r"<[^>]+>", " ", html)
        summary = re.sub(r"\s+", " ", plain).strip()[:400]

        pages.append(
            ContentPage(
                path=out_path,
                title=meta["title"],
                html=html,
                eyebrow=meta.get("eyebrow"),
                lede=meta.get("lede"),
                nav_group=meta.get("nav_group"),
                nav_label=meta.get("nav_label") or meta["title"],
                order=int(meta.get("order", 100)),
                meta=list(meta.get("meta") or []),
                badge=meta.get("badge"),
                toc=headings if meta.get("toc") else [],
                is_hub=bool(meta.get("hub")),
                summary=summary,
            )
        )

    hubs = [p for p in pages if p.is_hub]
    if len(hubs) > 1:
        names = ", ".join(sorted(p.title for p in hubs))
        raise ContentError(f"more than one page is marked `hub: true` ({names}).")

    return pages
