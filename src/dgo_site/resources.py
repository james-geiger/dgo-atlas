"""Paths to the files shipped inside the package."""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

SCHEMA_DIR = PACKAGE / "schema"
TEMPLATE = SCHEMA_DIR / "template.yaml"
VIEWMODEL = SCHEMA_DIR / "viewmodel.yaml"
CONFIG_SCHEMA = SCHEMA_DIR / "config.yaml"
CONFIG_JSON_SCHEMA = SCHEMA_DIR / "config.schema.json"

MODELS_DIR = PACKAGE / "models"
TEMPLATES = PACKAGE / "templates"
STATIC = PACKAGE / "static"
SCAFFOLD = PACKAGE / "scaffold"

ROOT_CLASS = "GovernanceRecord"
