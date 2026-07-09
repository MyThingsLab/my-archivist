from __future__ import annotations

import json
from pathlib import PurePath

from myarchivist.catalog import CatalogEntry


def to_json(entries: list[CatalogEntry]) -> str:
    return json.dumps(
        [
            {
                "title": e.title,
                "author": e.author,
                "isbn": e.isbn,
                "formats": list(e.formats),
                "subject": e.subject,
                "blurb": e.blurb,
                "shelf": e.shelf,
                "paths": list(e.paths),
            }
            for e in entries
        ],
        indent=2,
        sort_keys=True,
    )


def from_json(text: str) -> list[CatalogEntry]:
    rows = json.loads(text) if text.strip() else []
    return [
        CatalogEntry(
            title=row["title"],
            author=row["author"],
            isbn=row.get("isbn"),
            formats=tuple(row.get("formats", ())),
            subject=row.get("subject"),
            blurb=row.get("blurb", ""),
            shelf=row.get("shelf"),
            paths=tuple(row.get("paths", ())),
        )
        for row in rows
    ]


def render_markdown(entries: list[CatalogEntry]) -> str:
    out = ["# Catalog", ""]
    by_subject: dict[str, list[CatalogEntry]] = {}
    for e in entries:
        by_subject.setdefault(e.subject or "unsorted", []).append(e)
    for subject in sorted(by_subject):
        out.append(f"## {subject.replace('-', ' ').title()}")
        for e in by_subject[subject]:
            author = f" — {e.author}" if e.author else ""
            formats = f" [{', '.join(e.formats)}]"
            shelf = f" (shelf: {e.shelf})" if e.shelf else ""
            # Filenames, not full paths: the catalog is checked in and should
            # not encode one machine's directory layout.
            names = ", ".join(f"`{PurePath(p).name}`" for p in e.paths)
            files = f" — {names}" if names else ""
            out.append(f"- **{e.title}**{author}{formats}{shelf}{files}")
            if e.blurb:
                out.append(f"  {e.blurb}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
