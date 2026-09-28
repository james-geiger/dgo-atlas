# DGO Atlas reference

Govern a business glossary with the [Data Governance Ontology](https://github.com/james-geiger/dgo)
(DGO) and publish it as a static site.

DGO Atlas is the middle tier between DGO and an organization's glossary:

```
DGO (ontology)          github.com/james-geiger/dgo     imported by URL at the release each project names
   ▲
DGO Atlas (this)         Python package + CLI            template, validator, derivation, site, scaffold
   ▲
implementer repo        created by `dgo-atlas init`      governance YAML + dgo-atlas.yaml, nothing else
```

An implementer never writes LinkML, copies DGO files, or touches anything but
their data and config:

```bash
dgo-atlas init my-glossary      # scaffold: example data, config, CI, editor settings
                               # (also `dgo-atlas new project my-glossary`)
cd my-glossary
# ...write governance YAML under governance/...
dgo-atlas build                 # validate, derive, render, link-check
```

## Configuration

[`dgo-atlas.example.yaml`](../dgo-atlas.example.yaml) lists every setting
`dgo-atlas.yaml` accepts, with its description and default, including every
text key. It is generated (`uv run python -m dgo_atlas.generate`) from
`schema/config.yaml`, `text.yaml` and the defaults the code applies, and a
test fails if it drifts.

## Choosing a DGO release

DGO is not bundled. Each project names a DGO release in `dgo-atlas.yaml`:

```yaml
dgo_version: "0.1.1"
```

The authoring template imports that release's single-file schema straight
from the DGO repository, at
`https://raw.githubusercontent.com/james-geiger/dgo/refs/tags/<version>/dist/dgo.yaml`.
The pydantic model and the editor JSON Schema for it are generated at build
time.

- **Network.** Builds need network access to reach that URL. For offline
  builds, a mirror or a fork, set `dgo_source` to another URL or to a path
  (relative to `dgo-atlas.yaml`) of a single-file DGO schema.
- **Compatibility.** The build checks that the release has every class the
  derivation depends on (`dgo.REQUIRED_CLASSES`), and fails clearly if not.
  It warns about releases this version of DGO Atlas hasn't been tested with
  (`dgo.TESTED_VERSIONS`, which `dgo-atlas --version` lists).

## What it ships

| Part | Where |
| --- | --- |
| Authoring template: a root `GovernanceRecord` of lists, importing DGO | `src/dgo_atlas/schema/template.yaml` |
| DGO loading: release URL, runtime model and JSON Schema, and the facts read from DGO | `src/dgo_atlas/dgo.py` |
| View model: the pages' shape, in the `dgoatlas:` namespace | `src/dgo_atlas/schema/viewmodel.yaml` |
| Site config schema (`dgo-atlas.yaml`) | `src/dgo_atlas/schema/config.yaml` |
| Generated pydantic models for the view model and config, and the config's JSON Schema | `src/dgo_atlas/models/`, `schema/config.schema.json` |
| Validator: linkml-validate plus reference and rule checks | `src/dgo_atlas/validate.py` |
| Derivation: governance data → view model (handoff §5) | `src/dgo_atlas/derive.py` |
| Site renderer and templates | `src/dgo_atlas/render.py`, `templates/`, `static/` |
| CLI (Typer), one module per command group | `src/dgo_atlas/cli/` |
| Console output (Rich) for the CLI and the build | `src/dgo_atlas/console.py` |
| Implementer scaffold, and the code that copies it | `src/dgo_atlas/scaffold/`, `scaffold.py` |
| Editor JSON Schemas written into a project | `src/dgo_atlas/editor.py` |

## Exporting the data

`dgo-atlas convert` runs [`linkml-convert`](https://linkml.io/linkml/data/conversion.html)
on the project's data, for reuse outside the site. It validates and merges the
data files into one, then fills in the input, the template (`-s`), the root
class (`-C GovernanceRecord`) and the project's prefixes (`-P`). Every other
option goes to linkml-convert unchanged:

```bash
dgo-atlas convert -t ttl -o glossary.ttl       # RDF: each object an individual of its DGO class
dgo-atlas convert -t json-ld -o glossary.jsonld
dgo-atlas convert -t json > glossary.json
```

The RDF is what linkml-convert writes, including a blank-node
`dgoatlas:GovernanceRecord` that lists the objects. For linkml-convert to write
RDF at all, the template sets `default_range: string` and declares the DGO
release's prefixes, because LinkML takes neither from an imported schema.

## How a build works

1. **Config.** `dgo-atlas.yaml` is validated against `schema/config.yaml`, and
   its DGO release is loaded and checked.
2. **Read.** Every `.yaml` under the data directory is parsed; each is a
   partial `GovernanceRecord`. A `type` written as a DGO class name
   (`approved`, `submitted for review`, `owner`) is rewritten to that class's
   CURIE (`dgo:DGO_00000026`). The table comes from the release's own
   subclasses (`dgo.named_types`), no class is declared, and every later
   stage, the site and `dgo-atlas convert` see only DGO's value. The editor
   schema lists the names alongside the CURIEs.
3. **Shape.** Non-string scalars are rejected (unquoted dates, YAML booleans;
   DGO has no slots of those types, and `label` has no range, so
   linkml-validate alone would accept `label: yes`). Then each file is
   validated against the template with LinkML's validator, the same check as
   `linkml-validate -s template.yaml -C GovernanceRecord`. Bad `type` values
   get a suggestion (`dgo:Approved` → `approved`).
4. **Graph.** Files are merged. Ids must be unique and use a declared
   prefix. Every reference must resolve to an object of a kind the slot
   allows, including references inside a term's `responsibilities`. The
   allowed kinds are read from DGO, not restated. Then the rules:
   - `pref_label` must differ from every alt label.
   - A semantic type must be a full IRI or use a declared prefix.
   - `broader` must not form a cycle.
   - A term can have at most one creation.
   - No status boundary may come after a process closes.
5. **Derive.** Validated data is loaded into the generated pydantic model and
   turned into a view-model `Site`: state, domain, governing councils,
   history, pending changes, narrower terms, both-way `related`, council
   seats, organization members (and, read back, what each agent is a member
   of). Each semantic type is shown by what its class calls itself: its
   label and ontology are read from the EBI Ontology Lookup Service or,
   failing that, from the IRI dereferenced as RDF
   (`semantic.py`). A class neither describes is shown by its IRI, with a
   build note. The result is re-validated against `viewmodel.yaml`.
6. **Render.** Jinja templates render the site: terms, subject areas,
   domains, glossaries, councils, people and organizations, the governance
   process tree, a "How to read a term" page built from DGO's descriptions,
   and authored Markdown. Kinds (glossary term, owner, approved…) link to
   their DGO class IRIs; the site does not restate the ontology.
7. **Link check.** Every internal link must resolve.

The term-state rule (handoff §5.2) is provisional and lives in one function,
`derive.term_state`.

Only published terms are built. A term is published once a term creation is
recorded for it, whatever steps that creation has reached, unless the creation
was rejected (`derive.unpublished_reason`). Other terms, and links to them,
are left out of every page, and the build prints a note for each.

## Development

```bash
uv sync
uv run pytest
```

The tests need network access: they import DGO 0.1.1 from its release URL. They cover:
- the expected page facts on the variant fixture (`tests/fixtures/variant`: the
  handoff's example with its §5.3 variant, a deprecated term, and terms in
  review and drafted);
- which terms are published;
- each validator rule;
- loading DGO: the release URL, a local `dgo_source`, an unknown release, and
  a release missing classes;
- an end-to-end `init` → `build`;
- the command surface and exit codes, and that every CLI is Typer;
- that the generated files are current.

After changing `viewmodel.yaml` or `config.yaml`, regenerate the derived files:

```bash
uv run python -m dgo_atlas.generate
```

To build the fixture site and look at it:

```bash
uv run dgo-atlas build --project tests/fixtures/variant --out /tmp/dgo-atlas-preview
```

### Writing a command

Every command-line interface in this repository is [Typer](https://typer.tiangolo.com/):
no argparse, no raw click, no reading `sys.argv`. A test enforces this.

- **Where.** `src/dgo_atlas/cli/` has one module per group of commands:
  `project.py` (validate, build, convert, schema, text), `site.py` (linkcheck), and
  `new.py` (the `new` group, for scaffolding). Each module has its own
  `app = typer.Typer()`. `cli/__init__.py` only assembles them, so it shows
  the whole command surface. A new generator such as `new term` is one more
  function in `new.py`. A new group is a new module plus one `app.add_typer`
  line.
- **Thin.** A command parses its options, calls a library function, prints,
  and ends with `raise typer.Exit(code)` when the code can be non-zero. The
  logic lives in `build`, `scaffold`, `editor`, `linkcheck` and `text`, so it
  can be tested and reused without the CLI.
- **Options.** Declare them with `Annotated[..., typer.Option(help=...)]`. An
  option shared between commands, such as `--project`, is defined once in
  `cli/common.py`. The function's docstring is the command's help.
- **Output.** Print through `dgo_atlas.console` (`say`, `warn`, `note`,
  `error`, `fail`), never bare `print`. It prints user data with Rich markup
  off, so brackets in ids and YAML survive, and without hard wrapping.
- **Tests.** Invoke commands with `typer.testing.CliRunner` and check
  `exit_code`, `stdout` and `stderr`.

`python -m dgo_atlas.generate` is a Typer app of its own rather than a
`dgo-atlas` command, because it rewrites files inside the package, which in an
implementer's install would be site-packages.

### Supporting a new DGO release

1. Point the fixture's `dgo_version` at it and run the tests.
2. Fix whatever the change breaks, then add the release to `dgo.TESTED_VERSIONS`.

Never work around a DGO problem in the middleware: report it upstream. The
changes expected in DGO each have one home here:

| Expected DGO change | Where it lands |
| --- | --- |
| a new role or boundary kind | nothing: its class name works in `type` (`dgo.named_types`) |
| a new term slot | `viewmodel.yaml`, `derive.term_page`, `templates/term.html.j2` |
| `in_subject_area` multivalued | `derive.term_page` and the placement templates |
| the state rule confirmed or changed | `derive.term_state` |

## Decisions and limits

- **Identifiers.** The middleware's own schemas use `https://w3id.org/dgo-atlas/`
  (`dgoatlas:`). That w3id path is not registered, so it is an identifier only.
  Nothing is minted in `dgo:`.
- **Split data.** Implementers may split data across files; lists are
  concatenated. The scaffold puts each term and its lifecycle in its own file.
- **Editor schemas.** `dgo-atlas validate` and `dgo-atlas build` refresh
  `.dgo-atlas/*.schema.json` in the implementer repo when the DGO release or
  this package changes.
- **Wording.** Templates contain no literal copy. Every string comes from
  `src/dgo_atlas/text.yaml` through `t(key)`, and implementers override any
  key with `text:` in `dgo-atlas.yaml` (`dgo-atlas text` lists them). The four
  generated index pages also take their header and intro prose from a content
  file at the same path. DGO's own class names (owner, drafted…) and
  descriptions are shown as DGO has them. `tests/test_text.py` fails if a
  template uses a key the catalog doesn't have.
- **Identifier panel.** `show_identifiers: false` in `dgo-atlas.yaml` hides the
  id, IRI and DGO class on term, council and people pages, for sites that
  don't use IRIs. The "View source" link stays.
- **No history from git.** A term's history comes only from its status
  boundaries.
- **No extension.** Implementers extending DGO (their own role kinds, for
  example) is not supported yet.
- **No model reference.** This version doesn't publish schema documentation
  pages. `gen-doc` works on the template if they are wanted later.
- **CDN.** The default fonts load from Google Fonts.
