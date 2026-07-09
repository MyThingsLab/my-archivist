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


def test_scan_digital_pdf_decodes_utf16_title(tmp_path: Path) -> None:
    title_bytes = b"\xfe\xff" + "Statistical Learning".encode("utf-16-be")
    (tmp_path / "esl.pdf").write_bytes(b"%PDF-1.4\n/Title (" + title_bytes + b")\n")
    entries = scan_digital([tmp_path])
    assert entries[0].title == "Statistical Learning"


def test_scan_digital_pdf_strips_nul_padding_and_bomless_utf16(tmp_path: Path) -> None:
    padded = b"\xfe\xff" + "Padded Title".encode("utf-16-be") + b"\x00" * 12
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n/Title (" + padded + b")\n")
    bomless = "Bomless Title".encode("utf-16-be")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\n/Title (" + bomless + b")\n")
    titles = {e.title for e in scan_digital([tmp_path])}
    assert titles == {"Padded Title", "Bomless Title"}


def test_scan_digital_pdf_prefers_trailer_info_dict(tmp_path: Path) -> None:
    (tmp_path / "d.pdf").write_bytes(
        b"%PDF-1.4\n"
        b"3 0 obj\n<< /Title (Embedded Figure) >>\nendobj\n"
        b"7 0 obj\n<< /Title (The Real Book) /Author (Real Author) >>\nendobj\n"
        b"trailer\n<< /Info 7 0 R >>\n"
    )
    entries = scan_digital([tmp_path])
    assert entries[0].title == "The Real Book"
    assert entries[0].author == "Real Author"


def test_scan_digital_pdf_unresolvable_info_uses_filename(tmp_path: Path) -> None:
    # /Info names an object we can't read (e.g. compressed object stream);
    # the embedded /Title is known not to be the document's — use the filename.
    (tmp_path / "Actual_Book_Name.pdf").write_bytes(
        b"%PDF-1.4\n3 0 obj\n<< /Title (Embedded Figure) >>\nendobj\ntrailer\n<< /Info 42 0 R >>\n"
    )
    assert scan_digital([tmp_path])[0].title == "Actual Book Name"


def test_scan_digital_pdf_junk_author_dropped(tmp_path: Path) -> None:
    make_pdf_with_metadata(tmp_path / "c.pdf", title="Real Title", author="graphics")
    assert scan_digital([tmp_path])[0].author == ""


def test_scan_digital_pdf_junk_title_falls_back_to_filename(tmp_path: Path) -> None:
    esl = tmp_path / "Elements_of_Statistical_Learning.pdf"
    make_pdf_with_metadata(esl, title="Cover", author="")
    make_pdf_with_metadata(tmp_path / "nielsen_chuang.pdf", title="8348_013_fig_001.eps", author="")
    titles = {e.title for e in scan_digital([tmp_path])}
    assert titles == {"Elements of Statistical Learning", "nielsen chuang"}


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
