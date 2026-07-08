from __future__ import annotations

from pathlib import Path

from conftest import make_epub, make_pdf_with_metadata, make_pdf_without_metadata
from myarchivist.scanner import read_physical_intake, scan_digital


def test_scan_digital_reads_epub_metadata(tmp_path: Path) -> None:
    make_epub(tmp_path / "book.epub", title="Dune", author="Frank Herbert", isbn="9780441013593")
    entries = scan_digital([tmp_path])
    assert len(entries) == 1
    e = entries[0]
    assert e.title == "Dune"
    assert e.author == "Frank Herbert"
    assert e.isbn == "9780441013593"
    assert e.fmt == "digital"


def test_scan_digital_reads_pdf_metadata() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "report.pdf"
        make_pdf_with_metadata(path, title="Annual Report", author="Jane Doe")
        entries = scan_digital([d])
    assert len(entries) == 1
    assert entries[0].title == "Annual Report"
    assert entries[0].author == "Jane Doe"


def test_scan_digital_pdf_falls_back_to_filename(tmp_path: Path) -> None:
    make_pdf_without_metadata(tmp_path / "Jane Doe - Untitled Notes.pdf")
    entries = scan_digital([tmp_path])
    assert entries[0].title == "Untitled Notes"
    assert entries[0].author == "Jane Doe"


def test_scan_digital_ignores_other_extensions(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    assert scan_digital([tmp_path]) == []


def test_read_physical_intake_parses_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "intake.csv"
    csv_path.write_text("isbn,shelf\n9780441013593,A1\n", encoding="utf-8")
    entries = read_physical_intake(csv_path)
    assert len(entries) == 1
    assert entries[0].isbn == "9780441013593"
    assert entries[0].shelf == "A1"
    assert entries[0].fmt == "physical"


def test_read_physical_intake_title_author_row(tmp_path: Path) -> None:
    csv_path = tmp_path / "intake.csv"
    csv_path.write_text("title,author,shelf\nOld Book,Some Author,B2\n", encoding="utf-8")
    entries = read_physical_intake(csv_path)
    assert entries[0].title == "Old Book"
    assert entries[0].isbn is None
