"""The implementer's experience: init, add data, one command, a site."""

import re

from typer.testing import CliRunner

from dgo_atlas import dgo
from dgo_atlas.cli import app
from dgo_atlas.resources import SCAFFOLD

runner = CliRunner()


def dgo_atlas(*args):
    return runner.invoke(app, [str(a) for a in args])


def test_init_then_build(tmp_path):
    project = tmp_path / "glossary"
    assert dgo_atlas("init", project).exit_code == 0
    for rel in ["dgo-atlas.yaml", "governance/terms/clinical-trial.yaml", ".github/workflows/site.yml",
                ".vscode/settings.json", ".gitignore", ".dgo-atlas/governance.schema.json",
                ".dgo-atlas/config.schema.json", "content/index.md"]:
        assert (project / rel).is_file(), rel

    # Add a term in its own file, as an implementer would.
    (project / "governance" / "terms" / "trial-phase.yaml").write_text(
        "glossary_terms:\n"
        "  - id: term:trial-phase\n"
        "    label: trial phase\n"
        "    definition: The stage a clinical trial has reached.\n"
        "    part_of: glossary:glossary\n"
        "    in_subject_area: area:clinical-research\n"
        "    related: [term:clinical-trial]\n"
        "lifecycle_processes:\n"
        "  - id: process:trial-phase-creation\n"
        "    type: creation\n"
        "    label: Creation of \"trial phase\"\n"
        "    has_output: term:trial-phase\n"
        "    part_of: process:research-data-governance\n"
    )
    result = dgo_atlas("build", "--project", project)
    assert result.exit_code == 0, result.output
    assert (project / "site" / "terms" / "trial-phase.html").is_file()
    assert "Built" in result.stdout


def test_init_refuses_existing_project(tmp_path):
    assert dgo_atlas("init", tmp_path).exit_code == 0
    again = dgo_atlas("init", tmp_path)
    assert again.exit_code == 1
    assert "already exists" in again.stderr


def test_validate_reports_problems(tmp_path):
    dgo_atlas("init", tmp_path)
    path = tmp_path / "governance" / "terms" / "clinical-study.yaml"
    path.write_text(path.read_text().replace('"2026-09-20"', "2026-09-20"))
    result = dgo_atlas("validate", "--project", tmp_path)
    assert result.exit_code == 1
    assert "unquoted date" in result.stderr


def test_readme_type_table_matches_dgo():
    rows = re.findall(r"^\| (governance role|council role|status boundary) \| `([a-z ]+)` \| `(dgo:DGO_\d+)` \|$",
                      (SCAFFOLD / "README.md").read_text(), re.MULTILINE)
    expected = [(base, k.name, k.curie) for base in ("governance role", "council role", "status boundary")
                for k in dgo.subkinds(base)[1:]]
    assert sorted(rows) == sorted(expected)


def test_version_names_the_tested_dgo_releases():
    result = dgo_atlas("--version")
    assert result.exit_code == 0
    assert "Tested with Data Governance Ontology 0.3.0" in result.stdout


def test_scaffold_names_a_tested_dgo_release(tmp_path):
    dgo_atlas("init", tmp_path)
    text = (tmp_path / "dgo-atlas.yaml").read_text()
    assert f'dgo_version: "{dgo.TESTED_VERSIONS[-1]}"' in text
