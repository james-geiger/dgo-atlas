"""All site wording comes from the text catalog and can be overridden."""

import re
import shutil

import pytest
import yaml

from dgo_site import config
from dgo_site.build import build
from dgo_site.config import ConfigError
from dgo_site.resources import PACKAGE, STATIC, TEMPLATES
from dgo_site.text import Text, TextError, defaults

from .conftest import FIXTURES


def _used_keys() -> set[str]:
    """Every literal text key the templates and renderer ask for."""
    keys = set()
    sources = [p.read_text() for p in TEMPLATES.glob("*.j2")] + [(PACKAGE / "render.py").read_text()]
    for src in sources:
        # Literal keys only: keys built at runtime ("state." ~ state) end in "." here.
        keys |= {k for k in re.findall(r'\bt\("([a-z_.]+)"', src) if not k.endswith(".")}
        keys |= set(re.findall(r'self\.(?:text|plain)\("([a-z_.]+)"', src))
        for noun in re.findall(r'(?<![.\w])count\("([a-z_]+)"', src):
            keys |= {f"count.{noun}.one", f"count.{noun}.other"}
    keys |= {f"js.{k}" for k in re.findall(r'\bT\("([a-z_]+)"', (STATIC / "site.js").read_text())}
    return keys


def test_every_key_used_exists():
    missing = _used_keys() - set(defaults())
    assert not missing, f"used but not in text.yaml: {sorted(missing)}"


def test_placeholders_are_filled_and_escaped():
    t = Text({"term.recorded_as": "Known as <{name}>"})
    assert str(t("term.recorded_as", name="a & b")) == "Known as &lt;a &amp; b&gt;"
    assert str(t.count("term", 1)) == "1 term" and str(t.count("term", 3)) == "3 terms"


def test_unknown_key_suggests_the_closest():
    with pytest.raises(TextError, match="Did you mean term.history"):
        Text({"term.histroy": "x"})


def _project(tmp_path, *, text=None, content=None):
    root = tmp_path / "project"
    shutil.copytree(FIXTURES / "variant", root, ignore=shutil.ignore_patterns(".dgo-site", "site"))
    if text is not None:
        cfg = yaml.safe_load((root / config.CONFIG_NAME).read_text())
        cfg["text"] = text
        (root / config.CONFIG_NAME).write_text(yaml.safe_dump(cfg, allow_unicode=True))
    for rel, body in (content or {}).items():
        path = root / "content" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def test_unknown_key_in_config_is_a_config_error(tmp_path):
    root = _project(tmp_path, text={"home.brows_terms": "Find"})
    with pytest.raises(ConfigError, match="Did you mean home.browse_terms"):
        config.load(root / config.CONFIG_NAME)


def test_overrides_reach_pages_and_script(tmp_path):
    root = _project(tmp_path, text={
        "term.history": "Change log",
        "nav.directory": "Who's who",
        "count.term.other": "{n} definitions",
        "js.copied": "Done!",
        "state.approved.label": "Adopted",
    })
    out = tmp_path / "site"
    assert build(config.load(root / config.CONFIG_NAME), out=out) == 0
    term = (out / "terms" / "clinical-trial.html").read_text()
    assert ">Change log</h2>" in term and ">History<" not in term
    assert "Who&#39;s who" in term  # nav label, escaped
    assert "Adopted" in term
    assert '"copied": "Done!"' in term  # handed to site.js
    assert "4 definitions" in (out / "terms" / "index.html").read_text()


def test_content_file_sets_a_generated_page_header(tmp_path):
    root = _project(tmp_path, content={"directory.md": (
        "---\ntitle: Our people\neyebrow: Who we are\nlede: The people behind the glossary.\n---\n\n"
        "Ask any of them about **a term**.\n")})
    out = tmp_path / "site"
    assert build(config.load(root / config.CONFIG_NAME), out=out) == 0
    page = (out / "directory.html").read_text()
    assert '<h1 class="page-title">Our people</h1>' in page
    assert "Who we are" in page and "The people behind the glossary." in page
    assert "<strong>a term</strong>" in page  # body rendered as intro prose
    assert "Everyone who holds a governance role" not in page  # default lede replaced
    assert page.count('href="directory.html"') == 1  # listed once in the nav...
    assert ">Our people</a>" in page  # ...under its new title


def test_content_file_cannot_replace_other_generated_pages(tmp_path, capsys):
    root = _project(tmp_path, content={"terms/clinical-trial.md": "---\ntitle: Mine\n---\n"})
    assert build(config.load(root / config.CONFIG_NAME), out=tmp_path / "site") == 1
    assert "would replace a generated page" in capsys.readouterr().err
