"""Check an implementer's brand colours against WCAG 2.1 AA contrast.

The accent from `brand:` in dgo-atlas.yaml is used for link text, for white
text on buttons and the skip link, and for the focus outline, so a light
accent quietly makes the site fail WCAG. The build warns rather than fails:
the colour is the implementer's to choose, but they should know.

Only hex colours (#rgb, #rrggbb) are checked; other CSS colour syntax is
reported as unchecked.
"""

from __future__ import annotations

import re

from .models.config import Brand

TEXT_MINIMUM = 4.5  # WCAG 1.4.3, normal-size text

# The backgrounds the accent sits on, from site.css.
LIGHT = {"white": "#FFFFFF", "--bg-sub": "#F5F6F7"}
DARK = {"--bg": "#12171A", "--card": "#1C2428"}

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse(colour: str) -> tuple[int, int, int] | None:
    """An (r, g, b) triple for a hex colour, or None for anything else."""
    match = _HEX.match(colour.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """The WCAG contrast ratio between two colours, from 1 to 21."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _mix_white(rgb: tuple[int, int, int], share: float) -> tuple[int, int, int]:
    """`color-mix(in srgb, colour share, white)`, as site.css derives the dark accent."""
    return tuple(round(v * share + 255 * (1 - share)) for v in rgb)


def brand_problems(brand: Brand) -> list[str]:
    """One message per brand colour that falls short of AA, or can't be checked."""
    problems: list[str] = []
    if brand.accent:
        accent = parse(brand.accent)
        if accent is None:
            problems.append(f"brand.accent {brand.accent!r} is not a hex colour, so its contrast was not checked")
        else:
            for name, background in LIGHT.items():
                r = ratio(accent, parse(background))
                if r < TEXT_MINIMUM:
                    problems.append(f"brand.accent {brand.accent} has {r:.2f}:1 contrast with {name} "
                                    f"(WCAG AA needs {TEXT_MINIMUM}:1); links and buttons will be hard to read")
    # Dark mode uses accent_dark, or else the accent mixed half with white.
    dark, label = None, ""
    if brand.accent_dark:
        dark, label = parse(brand.accent_dark), f"brand.accent_dark {brand.accent_dark}"
        if dark is None:
            problems.append(f"brand.accent_dark {brand.accent_dark!r} is not a hex colour, "
                            "so its contrast was not checked")
    elif brand.accent and parse(brand.accent):
        dark, label = _mix_white(parse(brand.accent), 0.5), "the dark-mode accent (brand.accent lightened)"
    if dark is not None:
        for name, background in DARK.items():
            r = ratio(dark, parse(background))
            if r < TEXT_MINIMUM:
                problems.append(f"{label} has {r:.2f}:1 contrast with dark-mode {name} "
                                f"(WCAG AA needs {TEXT_MINIMUM}:1); set brand.accent_dark to a lighter colour")
    return problems
