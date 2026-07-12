from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

# Shared fakes come from mythings.testing (plain imports, no pytest_plugins:
# a top-level import alongside plugin registration would skip assertion
# rewriting). `clean_git_env` is imported so pytest registers the fixture.
from mythings.testing import (
    FakeGh,
    GitRepo,
    ScriptedEngine,
    fake_fetch,
    make_git_repo,
)

# Fixture re-export: pytest registers it under the attribute name, and the
# alias avoids shadowing errors in the autouse wrapper below.
from mythings.testing import clean_git_env as _shared_clean_git_env  # noqa: F401

from myarchivist.enrich import OPENLIBRARY_ENDPOINT

__all__ = ["ScriptedEngine"]


@pytest.fixture(autouse=True)
def _clean_git_env(request: pytest.FixtureRequest) -> None:
    # Every test builds real git repos; hook-launched pytest (pre-commit)
    # must not leak GIT_* into them.
    request.getfixturevalue("_shared_clean_git_env")


def make_repo(tmp_path: Path) -> Path:
    return make_git_repo(tmp_path, files={"README.md": "# library\n"}).path


def read_committed(repo: Path, branch: str, path: str) -> str:
    return GitRepo(path=repo, origin=repo.parent / "origin.git").read_committed(branch, path)


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
    # ISBN keys first so they win the substring match; any other Open Library
    # url falls through to the empty payload; non-openlibrary urls raise.
    responses: dict[str, object] = dict(payloads)
    responses[OPENLIBRARY_ENDPOINT] = {}
    return fake_fetch(responses)


empty_fetch = fake_fetch(default=b"{}")


def fake_gh(
    comment_url: str = "https://github.com/owner/name/issues/1#comment",
    *,
    open_bibliography_issues: list[dict] | None = None,
) -> FakeGh:
    # Stateful gh double: `pr list` reflects the PR a prior `pr create` opened,
    # `issue create` hands out increasing numbers — closures over `state`
    # replace the old FakeRunner subclass.
    state: dict[str, object] = {"opened_pr": None, "next_issue": 100}
    issues = open_bibliography_issues or []

    def pr_create(argv: list[str]) -> str:
        state["opened_pr"] = {"number": 9, "url": "https://github.com/owner/name/pull/9"}
        return "https://github.com/owner/name/pull/9\n"

    def pr_list(argv: list[str]) -> str:
        return json.dumps([state["opened_pr"]] if state["opened_pr"] else [])

    def issue_list(argv: list[str]) -> str:
        return json.dumps(
            [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "body": i.get("body", ""),
                    "labels": [{"name": "my-bibliography"}],
                    "url": f"https://github.com/owner/name/issues/{i['number']}",
                }
                for i in issues
            ]
        )

    def issue_create(argv: list[str]) -> str:
        state["next_issue"] = int(state["next_issue"]) + 1
        return f"https://github.com/owner/name/issues/{state['next_issue']}\n"

    return FakeGh(
        {
            ("issue", "comment"): comment_url + "\n",
            ("pr", "list"): pr_list,
            ("pr", "create"): pr_create,
            ("issue", "list"): issue_list,
            ("issue", "create"): issue_create,
            ("issue", "edit"): "",
        }
    )
