from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from mythings.http import Fetcher, http_get

from myarchivist.enrich import classify_subject, lookup_isbn, subjects_from_lookup
from myarchivist.scanner import RawEntry


@dataclass(frozen=True)
class CatalogEntry:
    title: str
    author: str
    isbn: str | None
    formats: tuple[str, ...]
    subject: str | None = None  # None until deterministic lookup or Engine assigns it
    blurb: str = ""
    shelf: str | None = None
    paths: tuple[str, ...] = field(default_factory=tuple)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _dedupe_key(entry: RawEntry) -> str:
    if entry.isbn:
        return f"isbn:{entry.isbn}"
    return f"ta:{_normalize(entry.title)}|{_normalize(entry.author)}"


def _entry_key(entry: CatalogEntry) -> str:
    if entry.isbn:
        return f"isbn:{entry.isbn}"
    return f"ta:{_normalize(entry.title)}|{_normalize(entry.author)}"


def carry_enrichment(entries: list[CatalogEntry], prior: list[CatalogEntry]) -> list[CatalogEntry]:
    """Keep enrichment already paid for: subjects/blurbs from the existing
    catalog stick to entries whose identity is unchanged, so a re-run against
    a weaker engine never degrades them. "unsorted" is the un-enriched marker,
    never carried — the entry stays eligible for classification."""
    by_key = {_entry_key(p): p for p in prior if p.subject is not None and p.subject != "unsorted"}
    out: list[CatalogEntry] = []
    for entry in entries:
        match = by_key.get(_entry_key(entry))
        if match is not None and entry.subject is None:
            entry = replace(entry, subject=match.subject, blurb=entry.blurb or match.blurb)
        out.append(entry)
    return out


def enrich_entries(
    entries: list[RawEntry], *, fetch: Fetcher = http_get
) -> tuple[list[RawEntry], dict[str, str | None]]:
    """Fill in title/author from Open Library where an ISBN is present.

    Returns the enriched entries plus a subject-per-ISBN map, so a subject the
    deterministic lookup already resolved survives dedup in `merge_entries`.
    """
    enriched: list[RawEntry] = []
    subjects_by_isbn: dict[str, str | None] = {}
    for entry in entries:
        if not entry.isbn:
            enriched.append(entry)
            continue
        data = lookup_isbn(entry.isbn, fetch=fetch)
        if data is None:
            enriched.append(entry)
            continue
        looked_up_title = (data.get("title") or "").strip()
        looked_up_author = ", ".join(
            a.get("name", "").strip() for a in data.get("authors", []) if a.get("name")
        )
        subjects_by_isbn[entry.isbn] = classify_subject(subjects_from_lookup(data))
        enriched.append(
            replace(
                entry,
                title=entry.title or looked_up_title,
                author=entry.author or looked_up_author,
            )
        )
    return enriched, subjects_by_isbn


def merge_entries(
    entries: list[RawEntry], *, subjects_by_isbn: dict[str, str | None] | None = None
) -> list[CatalogEntry]:
    subjects_by_isbn = subjects_by_isbn or {}
    groups: dict[str, list[RawEntry]] = {}
    for entry in entries:
        groups.setdefault(_dedupe_key(entry), []).append(entry)

    catalog: list[CatalogEntry] = []
    for group in groups.values():
        title = next((e.title for e in group if e.title), "")
        author = next((e.author for e in group if e.author), "")
        isbn = next((e.isbn for e in group if e.isbn), None)
        formats = tuple(sorted({e.fmt for e in group}))
        shelf = next((e.shelf for e in group if e.shelf), None)
        paths = tuple(e.path for e in group if e.path)
        subject = subjects_by_isbn.get(isbn) if isbn else None
        catalog.append(
            CatalogEntry(
                title=title,
                author=author,
                isbn=isbn,
                formats=formats,
                subject=subject,
                shelf=shelf,
                paths=paths,
            )
        )
    return sorted(catalog, key=lambda c: c.title.lower())
