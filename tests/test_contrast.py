"""Brand colours are checked against WCAG 2.1 AA text contrast."""

from dgo_atlas.contrast import brand_problems, parse, ratio
from dgo_atlas.models.config import Brand


def test_ratio_matches_wcag():
    assert round(ratio(parse("#000"), parse("#FFFFFF")), 2) == 21.0
    assert round(ratio(parse("#767676"), parse("#FFFFFF")), 2) == 4.54


def test_default_and_dark_accents_pass():
    assert brand_problems(Brand()) == []
    assert brand_problems(Brand(accent="#1D5C96")) == []


def test_light_accent_is_reported():
    problems = brand_problems(Brand(accent="#F2B705"))
    assert problems and all("brand.accent #F2B705" in p for p in problems)


def test_dark_accent_is_reported():
    assert any("brand.accent_dark #333333" in p for p in brand_problems(Brand(accent_dark="#333333")))


def test_named_colour_is_unchecked_not_wrong():
    assert brand_problems(Brand(accent="rebeccapurple")) == [
        "brand.accent 'rebeccapurple' is not a hex colour, so its contrast was not checked"]
