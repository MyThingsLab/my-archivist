# my-archivist

[![CI](https://github.com/MyThingsLab/my-archivist/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-archivist/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-archivist/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-archivist) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Maintains a unified catalog of a personal book/materials collection —
physical books on real shelves and digital files (PDF/EPUB) on disk — as
one cross-referenced, checked-in index: `catalog/CATALOG.md`
(human-browsable) + `catalog/catalog.json` (the source of truth).

**Not [MyLibrarian](../my-librarian)** — same "library" word, disjoint job.
MyLibrarian recommends software packages to depend on; MyArchivist catalogs
a human's own books/materials. No shared corpus, output, or code.

## How it works

Deterministic pre-work:

1. **Digital scan** (`--digital <dir>`, repeatable): walks a directory for
   `.pdf`/`.epub` files, extracting embedded metadata (EPUB `content.opf`
   via `zipfile` + `xml.etree`; PDF `/Info` dict via a minimal, best-effort
   byte-level reader), falling back to filename-derived title/author.
2. **Physical intake** (`--physical <intake.csv>`): a small human-maintained
   CSV (`isbn,shelf` or `title,author,shelf`) — this tool never invents a
   physical inventory.
3. **ISBN enrichment**: any entry with an ISBN and missing metadata is
   looked up via the keyless Open Library API.
4. **Dedupe + cross-reference**: matched by ISBN first, else normalized
   title+author — a title held in both formats becomes one entry with
   `formats: ["physical", "digital"]`.

If an entry still has no subject after deterministic lookup, **one Engine
call** assigns a tag (from a closed vocabulary) + a one-line blurb. Against
`NoopEngine`, it's cataloged as `tag="unsorted"` with no fabricated blurb.

Writes `catalog/CATALOG.md` + `catalog/catalog.json` inside a `Workspace`
worktree and opens exactly one PR per run, routed through `Policy` (`Guard`
default). Idempotent: a re-run with no new inputs is `outcome=skipped`, no
empty PR. Writes exactly one `kind=catalog` ledger entry per run. Never
merges.

## Usage

```bash
myarchivist scan --digital ~/Books --physical intake.csv --repo owner/name
myarchivist scan --digital ~/Books --no-pr --json   # dry run, no PR
```

## In the fleet loop

Standalone — a personal-use tool, per the
[design doc](../my-things-core/docs/tools/my-archivist.md). See the
[org README](../README.md) for how the shipped tools chain together.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
