"""The committed pydantic models and JSON Schemas match their LinkML sources."""

from dgo_site import generate


def test_generated_files_are_current():
    stale = generate.stale(write=False)
    assert stale == [], f"run `uv run python -m dgo_site.generate` ({', '.join(p.name for p in stale)})"
