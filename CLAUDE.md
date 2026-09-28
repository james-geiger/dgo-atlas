# dgo-site

## What this repository is

dgo-site is the middleware between the Data Governance Ontology (DGO) and
an organization's business glossary. It has two jobs:

1. **Translation.** It takes governance data that people can write and
   produces data that conforms to DGO, and it also works in the other
   direction. Implementers write plain YAML using readable names
   (`type: approved`, `type: owner`). dgo-site checks that YAML against a
   LinkML template that imports DGO, then rewrites each readable name as its
   exact DGO class CURIE (`dgo:DGO_00000026`). It resolves references, merges
   the files and derives the facts DGO leaves implicit: a term's state, its
   narrower terms, related terms in both directions, council seats and
   memberships. `dgo-site convert` then hands the result to `linkml-convert`,
   so it can be reused as JSON, JSON-LD or RDF individuals of DGO classes.
2. **Site generation.** It renders that derived view model as a static
   glossary site, using Jinja templates, a link checker and editor JSON
   Schemas.

```
DGO (ontology)        github.com/james-geiger/dgo      the source of truth; imported by URL at a release tag
   ▲
dgo-site (this repo)  Python package + Typer CLI       template, validator, translation, derivation, site, scaffold, export
   ▲
implementer repo      created by `dgo-site init`       governance YAML + dgo-site.yaml, nothing else
```

An implementer never writes LinkML, copies DGO files or edits templates. Each
implementer repo holds only data (`governance/**/*.yaml`), authored Markdown
(`content/`) and `dgo-site.yaml`. If an implementer would have to touch
anything else to get a result, dgo-site is missing a feature.

### The role of DGO

- **DGO is upstream and authoritative.** DGO defines the classes, slots,
  ranges and descriptions; dgo-site reads them. Look up ontology facts through
  `dgo.py` (`dgo.view()`, `named_types`, `reference_slots`,
  `slot_description`, `REQUIRED_CLASSES`) and never restate them in code,
  templates or copy. The site links each kind to its DGO class IRI and shows
  DGO's own class names and descriptions.
- **Import it, never vendor it.** Each project sets `dgo_version` in
  `dgo-site.yaml`. `dgo.use()` puts that release's `dist/dgo.yaml` from the
  DGO repo in place of the `DGO_IMPORT` placeholder in `schema/template.yaml`.
  The pydantic model and JSON Schema are generated at runtime. Use only
  published release tags, never branches or unpushed commits. `dgo_source`
  overrides the URL for mirrors and offline builds.
- **Mint nothing in `dgo:`.** dgo-site's own schemas use `dgosite:`
  (`https://w3id.org/dgo-site/`, which is an identifier only and isn't
  registered). The template adds only a `GovernanceRecord` root made of lists.
  Readable type names are a lookup from DGO's own subclass names, not new
  classes or enums.
- **Report DGO problems upstream.** Don't work around a DGO problem in the
  middleware. If DGO looks wrong or is missing something, say so and suggest
  the upstream change. The user maintains DGO too.
- **Adding a DGO release:** bump `dgo_version` in `tests/fixtures/variant`,
  run the tests, fix what breaks, then add the release to
  `dgo.TESTED_VERSIONS`. The table "Supporting a new DGO release" in `docs/reference.md` says
  where each kind of expected DGO change lands.

### Implementers

`~/Repositories/unmc/data-governance` is the first real implementer. It has
already migrated and pins `dgo-site @ git+...@v<tag>` in its `pyproject.toml`.
Don't break features it relies on, and don't leak its institution-specific
details (names, colours such as `#AD122A`) into the scaffold, fixtures or
defaults. dgo-site's defaults use a neutral palette.

## How a build flows

"How a build works" in `docs/reference.md` has the full details. In brief:

| Stage | Module |
| --- | --- |
| Load and validate `dgo-site.yaml`, then load and check the DGO release | `config.py`, `dgo.py` |
| Read and merge the data files, and turn readable `type` names into CURIEs | `loader.py`, `dgo.py` |
| Shape (linkml-validate against the template), references and rules | `validate.py` |
| Derive the view model (`schema/viewmodel.yaml`, `dgosite:`) | `derive.py`, `semantic.py` |
| Render and link-check | `render.py`, `templates/`, `static/`, `linkcheck.py` |
| Export via linkml-convert | `convert.py` |
| Orchestration | `build.py` |

Rules to keep:

- **Publishing.** A term enters the site only once a term creation is
  recorded for it and that creation hasn't been rejected
  (`derive.unpublished_reason`). A term may go straight to approved. There are
  no "unrecorded" or "rejected" pages; unpublished terms and links to them
  are dropped, and the build prints a note.
- **State.** The term-state rule is provisional and lives only in
  `derive.term_state`. A term has no status field; its state comes from its
  lifecycle boundaries.
- **Follow relationships instead of repeating lists.** For example, a council
  page lists the subject areas that hold terms it governs, not every term
  again.
- **Semantic types** are shown by what the referenced class calls itself
  (OLS, then the IRI dereferenced as RDF). Fall back to the IRI and a build
  note; never make up a label.
- **Export stays thin.** `convert` passes through to `linkml-convert`. It
  fills in only the input, `-s`, `-C` and `-P`, and forwards everything else
  unchanged. Don't reimplement serialization.
- **Prefer LinkML's own tooling** (linkml-validate, linkml-convert, gen-doc,
  the pydantic generator) to bespoke code. There is no model-reference page
  in this version; if it comes back, use `gen-doc -f html` with templates.

## Configuration and wording

- Every setting lives in `schema/config.yaml` and every visible string in
  `text.yaml`, read through `t(key)`. Templates contain no literal copy, and
  implementers override any key with `text:`. Copy that dgo-site writes must
  always be overridable. Generated index pages also take a header and intro
  from a content file at the same path.
- `dgo-site.example.yaml` at the repo root lists every setting at its
  default. It is generated, and a test fails if it drifts. After changing
  `config.yaml`, `viewmodel.yaml` or `text.yaml`, run
  `uv run python -m dgo_site.generate`. Don't hide configuration behind the
  CLI. If a setting exists, it must appear in the example file.

## Command-line interfaces

Every CLI in this repository uses Typer. Do not add argparse, raw click
decorators or `sys.argv` parsing: `tests/test_cli.py::test_every_cli_is_typer`
fails if they appear under `src/`. Before adding a new script or entry point,
ask whether it belongs as a command in `src/dgo_site/cli/`.

- Commands live in `src/dgo_site/cli/`, one module per group, each with its
  own `app = typer.Typer()`. `cli/__init__.py` only assembles them.
  Scaffolding generators go in `cli/new.py` (`dgo-site new <thing>`).
- Keep commands thin. Parse options, call a library function (`build`,
  `scaffold`, `editor`, `linkcheck`, `convert`, `text`, ...), print, and
  `raise typer.Exit(code)`. Put the logic in the library module, not the
  command.
- Declare options with `Annotated[..., typer.Option(help=...)]`. Shared
  options, such as `--project`, live in `cli/common.py`. The docstring is the
  command's help.
- Print through `dgo_site.console`, never bare `print`.
- Test commands with `typer.testing.CliRunner`.

`python -m dgo_site.generate` is the one separate Typer app, because it
rewrites files inside the package. See "Writing a command" in `docs/reference.md`.

## Development

```bash
uv sync
uv run pytest            # needs network: imports DGO from its release URL
uv run python -m dgo_site.generate   # after changing schema/viewmodel.yaml, schema/config.yaml or text.yaml
```

- **One fixture.** `tests/fixtures/variant` is the only test fixture, and it
  is also the preview site. Add test cases to it, or to a modified copy made
  inside a test (see the `broken` fixture in `conftest.py`). Don't add new
  fixture directories.
- **Preview.** The `preview` entry in `.claude/launch.json` builds the variant
  into `.preview/` and serves it. Use it after any change to templates, CSS or
  derivation.
- **Stale references.** `docs/reference.md` and the code cite "handoff §5" for the
  original design. That handoff is no longer in the DGO repo, so treat the
  reference and this file as current. `README.md` is for newcomers: keep it
  short (under 250 words, plain language) and put details in the reference.
