from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from mythings.engine import EngineRequest, EngineResult

from myarchivist.enrich import OPENLIBRARY_ENDPOINT


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True)


def make_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "work"
    repo.mkdir()
    (repo / "README.md").write_text("# library\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Archivist")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "init")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")
    return repo


def read_committed(repo: Path, branch: str, path: str) -> str:
    origin = repo.parent / "origin.git"
    proc = subprocess.run(
        ["git", "-C", str(origin), "show", f"{branch}:{path}"], capture_output=True, text=True
    )
    return proc.stdout


def make_epub(path: Path, *, title: str, author: str, isbn: str | None = None) -> None:
    identifier = f'<dc:identifier opf:scheme="ISBN">{isbn}</dc:identifier>' if isbn else ""
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    {identifier}
  </metadata>
</package>
"""
    container = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("content.opf", opf)


def make_pdf_with_metadata(path: Path, *, title: str, author: str) -> None:
    path.write_bytes(f"%PDF-1.4\n/Title ({title})\n/Author ({author})\n".encode())


def make_pdf_without_metadata(path: Path) -> None:
    path.write_bytes(b"%PDF-1.4\nno metadata here\n")


def openlibrary_payload(isbn: str, *, title: str, author: str, subjects: list[str]) -> dict:
    return {
        f"ISBN:{isbn}": {
            "title": title,
            "authors": [{"name": author}],
            "subjects": [{"name": s} for s in subjects],
        }
    }


def fake_fetch_factory(payloads: dict[str, dict]):
    def _fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
        if url.startswith(OPENLIBRARY_ENDPOINT):
            for isbn, payload in payloads.items():
                if f"ISBN:{isbn}" in url or isbn in url:
                    return json.dumps(payload).encode()
            return json.dumps({}).encode()
        raise AssertionError(f"unexpected fetch url: {url}")

    return _fetch


def empty_fetch(url: str, *, data: bytes | None = None, headers: dict | None = None) -> bytes:
    return json.dumps({}).encode()


class ScriptedEngine:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text=self.reply)


class SpyEngine:
    def __init__(self) -> None:
        self.calls: list[EngineRequest] = []

    def run(self, request: EngineRequest) -> EngineResult:
        self.calls.append(request)
        return EngineResult(text="")


class FakeRunner:
    def __init__(self, comment_url: str = "https://github.com/owner/name/issues/1#comment") -> None:
        self.calls: list[list[str]] = []
        self._comment_url = comment_url
        self._opened_pr: dict | None = None

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["issue", "comment"]:
            return self._comment_url + "\n"
        if argv[:2] == ["pr", "list"]:
            return json.dumps([self._opened_pr] if self._opened_pr else [])
        if argv[:2] == ["pr", "create"]:
            self._opened_pr = {"number": 9, "url": "https://github.com/owner/name/pull/9"}
            return self._opened_pr["url"] + "\n"
        raise AssertionError(f"unexpected gh call: {argv}")
