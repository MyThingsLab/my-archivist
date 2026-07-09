from __future__ import annotations

from myarchivist.catalog import CatalogEntry
from myarchivist.render import from_json, render_markdown, to_json

_ENTRIES = [
    CatalogEntry(
        "Dune",
        "Frank Herbert",
        "123",
        ("physical", "digital"),
        subject="fiction",
        blurb="A desert epic.",
        shelf="A1",
        paths=("/x/dune.epub",),
    ),
    CatalogEntry("Untitled Notes", "", None, ("digital",), subject=None),
]


def test_to_json_round_trips_through_from_json() -> None:
    text = to_json(_ENTRIES)
    restored = from_json(text)
    assert restored == _ENTRIES


def test_from_json_handles_empty_string() -> None:
    assert from_json("") == []


def test_render_markdown_groups_by_subject_and_includes_blurb() -> None:
    text = render_markdown(_ENTRIES)
    assert "## Fiction" in text
    assert "**Dune** — Frank Herbert" in text
    assert "A desert epic." in text
    assert "## Unsorted" in text  # subject=None entries render under "unsorted"


def test_render_markdown_shows_filenames_not_full_paths() -> None:
    text = render_markdown(_ENTRIES)
    assert "`dune.epub`" in text
    assert "/x/dune.epub" not in text
