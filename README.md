# DGO Atlas

Publish your organization's business glossary as a website, with a clear
record of who owns each term and how it was approved.

## What it does

A business glossary gives shared definitions for the words an organization
uses in its data: what counts as a "clinical trial," an "active student" or
"direct costs." Keeping those definitions consistent is hard when they live
in spreadsheets and wikis, where it isn't clear who owns a definition, whether
it's approved, or when it last changed.

With Atlas, you keep the glossary in plain text files in a Git repository.
Each term records its definition, who is responsible for it, and every step
of its review. Atlas checks the files for mistakes, such as a term that
refers to an owner who doesn't exist, and then builds a searchable static
website you can host anywhere, including GitHub Pages.

Because the glossary lives in Git, every change goes through a pull request
and has a full history.

## Built on a shared standard

Your files follow the
[Data Governance Ontology](https://github.com/james-geiger/dgo) (DGO). DGO is
a published vocabulary that defines the parts of data governance, such as
terms, owners, stewards, councils and approval steps, and how they relate to
each other. You write in everyday words like `owner` or `approved`, and
Atlas translates them into DGO's standard definitions. That means other
tools can read and reuse your glossary without guessing what your fields
mean.

## Get started

You need [uv](https://docs.astral.sh/uv/), a Python package manager.

```bash
uvx dgo-atlas init my-glossary
cd my-glossary
uv run dgo-atlas build
```

Open `site/index.html` to see the result. The new project includes example
terms, a sample council and a GitHub Actions workflow that builds the site on
every pull request.

Here is a small part of an example term:

```yaml
glossary_terms:
  - id: org:clinical-trial
    label: clinical trial
    definition: A research study in which participants are assigned to interventions...
    responsibilities:
      - type: owner
        role_of: org:research-office
```

## Everyday commands

| Command | What it does |
| --- | --- |
| `dgo-atlas validate` | Check your files for mistakes |
| `dgo-atlas build` | Check your files, then build the site |
| `dgo-atlas convert -t ttl` | Export the glossary for other data tools |
| `dgo-atlas text` | List the site's wording, all of which you can change |

## Settings

Titles, colors, fonts and page wording are customizable by changing the values in `dgo-atlas.yaml`. Every setting and its default is listed in
[dgo-atlas.example.yaml](dgo-atlas.example.yaml).

## Learn more

- [DGO](https://github.com/james-geiger/dgo): the vocabulary your files follow


## License

[MIT](LICENSE)
