from __future__ import annotations

from conftest import empty_fetch, fake_fetch_factory, openlibrary_payload
from myarchivist.catalog import enrich_entries, merge_entries
from myarchivist.scanner import RawEntry


def test_enrich_fills_title_author_from_isbn_lookup() -> None:
    raw = [RawEntry(title="", author="", isbn="123", fmt="physical", shelf="A1")]
    fetch = fake_fetch_factory(
        {
            "123": openlibrary_payload(
                "123", title="Dune", author="Frank Herbert", subjects=["Science fiction"]
            )
        }
    )
    enriched, subjects = enrich_entries(raw, fetch=fetch)
    assert enriched[0].title == "Dune"
    assert enriched[0].author == "Frank Herbert"
    assert subjects["123"] == "fiction"


def test_enrich_leaves_entries_without_isbn_untouched() -> None:
    raw = [RawEntry(title="Some Book", author="Some Author", isbn=None, fmt="digital")]
    enriched, subjects = enrich_entries(raw, fetch=empty_fetch)
    assert enriched == raw
    assert subjects == {}


def test_enrich_handles_unknown_isbn() -> None:
    raw = [RawEntry(title="Mystery Book", author="", isbn="999", fmt="physical")]
    enriched, subjects = enrich_entries(raw, fetch=empty_fetch)
    assert enriched[0].title == "Mystery Book"  # kept as-is, no crash
    assert "999" not in subjects


def test_merge_dedupes_by_isbn_across_formats() -> None:
    raw = [
        RawEntry(title="Dune", author="Frank Herbert", isbn="123", fmt="physical", shelf="A1"),
        RawEntry(
            title="Dune", author="Frank Herbert", isbn="123", fmt="digital", path="/x/dune.epub"
        ),
    ]
    merged = merge_entries(raw)
    assert len(merged) == 1
    assert merged[0].formats == ("digital", "physical")
    assert merged[0].shelf == "A1"
    assert merged[0].paths == ("/x/dune.epub",)


def test_merge_dedupes_by_normalized_title_author_without_isbn() -> None:
    raw = [
        RawEntry(title="Dune ", author="Frank Herbert", isbn=None, fmt="physical"),
        RawEntry(title="dune", author="frank herbert", isbn=None, fmt="digital"),
    ]
    merged = merge_entries(raw)
    assert len(merged) == 1
    assert merged[0].formats == ("digital", "physical")


def test_merge_keeps_distinct_titles_separate() -> None:
    raw = [
        RawEntry(title="Dune", author="Frank Herbert", isbn=None, fmt="physical"),
        RawEntry(title="Foundation", author="Isaac Asimov", isbn=None, fmt="physical"),
    ]
    merged = merge_entries(raw)
    assert len(merged) == 2


def test_merge_applies_subjects_by_isbn() -> None:
    raw = [RawEntry(title="Dune", author="Frank Herbert", isbn="123", fmt="physical")]
    merged = merge_entries(raw, subjects_by_isbn={"123": "fiction"})
    assert merged[0].subject == "fiction"


def test_carry_enrichment_keeps_prior_subject_and_blurb() -> None:
    from myarchivist.catalog import CatalogEntry, carry_enrichment

    prior = [
        CatalogEntry("Dune", "Frank Herbert", None, ("digital",), subject="fiction", blurb="Epic."),
        CatalogEntry("Old Notes", "", None, ("digital",), subject="unsorted"),
    ]
    fresh = [
        CatalogEntry("Dune", "Frank Herbert", None, ("digital",)),
        CatalogEntry("Old Notes", "", None, ("digital",)),
        CatalogEntry("New Book", "", None, ("digital",)),
    ]
    out = carry_enrichment(fresh, prior)
    assert out[0].subject == "fiction"
    assert out[0].blurb == "Epic."
    # "unsorted" is the un-enriched marker: not carried, stays classifiable
    assert out[1].subject is None
    assert out[2].subject is None
