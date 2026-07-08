# my-archivist — agent instructions

You are developing **my-archivist**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** maintains a unified catalog of a personal book/materials
  collection — physical books (via ISBN → Open Library lookup) and digital
  files (PDF/EPUB scanned on disk) — as one cross-referenced,
  checked-in index (`catalog/CATALOG.md` + `catalog/catalog.json`), deduping
  titles held in both formats. **Not MyLibrarian** (which recommends
  software packages) — see the design doc:
  [`my-things-core/docs/tools/my-archivist.md`](../my-things-core/docs/tools/my-archivist.md).
- **The single Engine call:** one per invocation, optional. "Given this
  book's title/author/description, assign one subject tag from a closed
  vocabulary + a one-line blurb" — used only for entries with no
  deterministic subject (from Open Library subjects or digital metadata).
  Against `NoopEngine`, entries get `tag="unsorted"`, no blurb.
- **Invariants / rules:** exactly one Engine call per run (only for entries
  needing enrichment); all metadata lookup is deterministic, LLM-free HTTP
  (Open Library, keyless) plus local PDF/EPUB parsing — no new runtime SDK.
  Physical holdings come only from a human-maintained intake CSV — this
  tool never invents an inventory. Writes `catalog/CATALOG.md` +
  `catalog/catalog.json` inside a `Workspace` and opens exactly one PR per
  run (idempotent: a re-run with no new inputs is `outcome=skipped`, no
  empty PR), routed through `Policy` (`Guard` default). **Never merges.**
  Ledger `kind`: `catalog`.
- **Backlog label:** `my-archivist`
