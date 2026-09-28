import shutil
from pathlib import Path

import pytest

from dgo_site import config, dgo
from dgo_site.derive import Deriver
from dgo_site.validate import validate

FIXTURES = Path(__file__).parent / "fixtures"
EX = {"ex": "https://w3id.org/dgo/data/"}
DGO_VERSION = "0.1.0"  # imported from the DGO repository; the tests need network access


@pytest.fixture(scope="session", autouse=True)
def active_dgo():
    """Every test runs against the DGO release the fixtures name."""
    dgo.use(dgo.source_for(DGO_VERSION))
    return dgo.active()


def load(name: str):
    """Validate a fixture project; return its Deriver and derived view model."""
    project = config.load(FIXTURES / name / config.CONFIG_NAME)
    report = validate(project.data_dir, project.root, project.prefixes)
    assert report.ok, [str(e) for e in report.errors]
    deriver = Deriver(report.record, project.prefixes)
    return deriver, deriver.site()


@pytest.fixture(scope="session")
def variant():
    return load("variant")


@pytest.fixture
def broken(tmp_path):
    """Copy the variant's data into a temp data dir, edit it, and validate it.

    Pass (old, new) replacements, applied to governance.yaml; add files with
    extra={name: text}; leave files out with drop=[name, ...].
    """
    source = FIXTURES / "variant" / "governance"

    def run(*replacements, extra=None, drop=()):
        data = tmp_path / "governance"
        shutil.rmtree(data, ignore_errors=True)
        shutil.copytree(source, data)
        for name in drop:
            (data / name).unlink()
        text = (data / "governance.yaml").read_text()
        for old, new in replacements:
            assert old in text, f"fixture text not found: {old!r}"
            text = text.replace(old, new)
        (data / "governance.yaml").write_text(text)
        for name, body in (extra or {}).items():
            (data / name).write_text(body)
        return validate(data, tmp_path, EX)

    return run
