from __future__ import annotations

import csv
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

_OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}

# A best-effort, dependency-free reader over the raw PDF bytes: many PDFs keep
# their /Info dict as an uncompressed literal string even when content streams
# are compressed, so this regex catches a useful fraction without a PDF
# library. Anything it misses falls back to the filename heuristic below —
# never a fatal condition (harness: dependency-free runtime).
_PDF_TITLE = re.compile(rb"/Title\s*\(((?:[^()\\]|\\.)*)\)")
_PDF_AUTHOR = re.compile(rb"/Author\s*\(((?:[^()\\]|\\.)*)\)")

_ISBN_DIGITS = re.compile(r"[\dXx]{10,13}")

# PDF /Title values that are producer artifacts, not book titles: placeholder
# words, or a stray source-file name (figure .eps, InDesign .indd, ...) left
# by the typesetting pipeline. Fall back to the filename for these.
_JUNK_TITLES = frozenset({"untitled", "cover", "title", "unknown", "book", "front cover"})
_JUNK_TITLE_SUFFIX = re.compile(
    r"\.(eps|indd|dvi|tif+|png|jpe?g|ai|fig|docx?|tex|qxd)$", re.IGNORECASE
)
_JUNK_AUTHORS = frozenset({"author", "graphics", "unknown"})
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class RawEntry:
    title: str
    author: str
    isbn: str | None
    fmt: str  # "physical" | "digital"
    shelf: str | None = None
    path: str | None = None


def _decode_pdf_string(raw: bytes) -> str:
    unescaped = re.sub(rb"\\([()\\])", rb"\1", raw)
    if unescaped.startswith(b"\xfe\xff"):
        # UTF-16BE text string (PDF 32000-1 §7.9.2.2), marked by a BOM.
        text = unescaped[2:].decode("utf-16-be", errors="replace")
    elif b"\x00" in unescaped:
        # NUL bytes never appear in PDFDocEncoded strings; this is UTF-16BE
        # from a producer that skipped the BOM.
        text = unescaped.decode("utf-16-be", errors="replace")
    else:
        text = unescaped.decode("latin-1", errors="replace")
    # NUL padding and other control bytes crash downstream consumers (the
    # Engine subprocess argv rejects embedded NULs) — drop them, always.
    return _CONTROL_CHARS.sub("", text).strip()


def _is_junk_title(title: str) -> bool:
    return title.lower() in _JUNK_TITLES or bool(_JUNK_TITLE_SUFFIX.search(title))


def _filename_fallback(path: Path) -> tuple[str, str]:
    stem = path.stem.replace("_", " ").strip()
    if " - " in stem:
        author, _, title = stem.partition(" - ")
        return title.strip(), author.strip()
    return stem, ""


def read_pdf_metadata(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    title_match = _PDF_TITLE.search(data)
    author_match = _PDF_AUTHOR.search(data)
    title = _decode_pdf_string(title_match.group(1)) if title_match else ""
    author = _decode_pdf_string(author_match.group(1)) if author_match else ""
    if author.lower() in _JUNK_AUTHORS:
        author = ""
    if not title or _is_junk_title(title):
        title, fallback_author = _filename_fallback(path)
        author = author or fallback_author
    return title, author


def _extract_isbn(identifier_text: str) -> str | None:
    match = _ISBN_DIGITS.search(identifier_text.replace("-", ""))
    return match.group(0) if match else None


def read_epub_metadata(path: Path) -> tuple[str, str, str | None]:
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", _CONTAINER_NS)
        opf_path = rootfile.get("full-path") if rootfile is not None else None
        if not opf_path:
            title, author = _filename_fallback(path)
            return title, author, None
        opf = ET.fromstring(zf.read(opf_path))
        metadata = opf.find("opf:metadata", _OPF_NS)
        title = (
            metadata.findtext("dc:title", default="", namespaces=_OPF_NS)
            if metadata is not None
            else ""
        ).strip()
        author = (
            metadata.findtext("dc:creator", default="", namespaces=_OPF_NS)
            if metadata is not None
            else ""
        ).strip()
        isbn = None
        if metadata is not None:
            for ident in metadata.findall("dc:identifier", _OPF_NS):
                candidate = _extract_isbn(ident.text or "")
                if candidate:
                    isbn = candidate
                    break
        if not title:
            title, fallback_author = _filename_fallback(path)
            author = author or fallback_author
        return title, author, isbn


def scan_digital(dirs: Iterable[str | Path]) -> list[RawEntry]:
    entries: list[RawEntry] = []
    for d in dirs:
        base = Path(d)
        for path in sorted(base.rglob("*")):
            if path.suffix.lower() == ".epub":
                title, author, isbn = read_epub_metadata(path)
            elif path.suffix.lower() == ".pdf":
                title, author = read_pdf_metadata(path)
                isbn = None
            else:
                continue
            entries.append(
                RawEntry(title=title, author=author, isbn=isbn, fmt="digital", path=str(path))
            )
    return entries


def read_physical_intake(csv_path: str | Path) -> list[RawEntry]:
    entries: list[RawEntry] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            entries.append(
                RawEntry(
                    title=(row.get("title") or "").strip(),
                    author=(row.get("author") or "").strip(),
                    isbn=(row.get("isbn") or "").strip() or None,
                    fmt="physical",
                    shelf=(row.get("shelf") or "").strip() or None,
                )
            )
    return entries
