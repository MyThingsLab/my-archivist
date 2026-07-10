from __future__ import annotations

from pathlib import Path

from mythings.ledger import Ledger
from mythings.policy import ALLOW, Action, PolicyResult

from conftest import FakeRunner, ScriptedEngine, empty_fetch, make_epub, make_repo, read_committed
from myarchivist.archivist import Archivist


class _AllowPolicy:
    def evaluate(self, action: Action) -> PolicyResult:
        return ALLOW


def test_scan_skips_when_nothing_given(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    archivist = Archivist(
        source=repo, ledger=ledger, engine=ScriptedEngine("{}"), policy=_AllowPolicy()
    )
    result = archivist.scan()
    assert result.outcome == "skipped"


def test_scan_writes_catalog_and_opens_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="123")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)])
    assert result.outcome == "success"
    assert result.pr == 9
    assert result.new_entries == 1

    committed = read_committed(repo, "my-archivist/catalog", "catalog/CATALOG.md")
    assert "Dune" in committed

    entries = ledger.read(tool="myarchivist", kind="catalog")
    assert entries[0].outcome == "success"


def test_scan_no_pr_writes_locally_without_pushing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="123")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)], no_pr=True)
    assert result.outcome == "success"
    assert result.pr is None

    import subprocess

    local = subprocess.run(
        ["git", "-C", str(repo), "show", "my-archivist/catalog:catalog/CATALOG.md"],
        capture_output=True,
        text=True,
    )
    assert local.returncode == 0
    assert "Dune" in local.stdout
    assert read_committed(repo, "my-archivist/catalog", "catalog/CATALOG.md") == ""

    second = archivist.scan(digital=[str(books)], no_pr=True)
    assert second.outcome == "skipped"


def test_scan_idempotent_second_run_skips(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="123")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    first = archivist.scan(digital=[str(books)])
    assert first.outcome == "success"

    second = archivist.scan(digital=[str(books)])
    assert second.outcome == "skipped"
    # only one pr create call across both runs
    assert sum(1 for c in runner.calls if c[:2] == ["pr", "create"]) == 1


def test_scan_comments_on_issue_when_given(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="123")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)], issue=5)
    assert result.comment_url is not None
    assert any(c[:2] == ["issue", "comment"] for c in runner.calls)


def test_scan_files_bibliography_issue_for_new_isbn(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="9780441172719")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)])
    assert result.outcome == "success"

    creates = [c for c in runner.calls if c[:2] == ["issue", "create"]]
    assert len(creates) == 1
    assert "bibliography: catalog isbn:9780441172719" in creates[0]
    edits = [c for c in runner.calls if c[:2] == ["issue", "edit"]]
    assert edits and "my-bibliography" in edits[0]

    entries = ledger.read(tool="myarchivist", kind="catalog")
    assert entries[0].data["bibliography_issues"] == [{"isbn": "9780441172719", "issue": 101}]


def test_scan_does_not_refile_isbn_already_cataloged(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="9780441172719")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    assert archivist.scan(digital=[str(books)]).outcome == "success"

    make_epub(
        books / "herbert2.epub", title="Dune Messiah", author="Frank Herbert",
        isbn="9780425093372",
    )
    result = archivist.scan(digital=[str(books)])
    assert result.outcome == "success"

    # Only the newly-added ISBN gets a bibliography issue on the second run.
    creates = [c for c in runner.calls if c[:2] == ["issue", "create"]]
    assert len(creates) == 2
    assert "bibliography: catalog isbn:9780441172719" in creates[0]
    assert "bibliography: catalog isbn:9780425093372" in creates[1]


def test_scan_no_bibliography_flag_skips_filing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="9780441172719")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)], no_bibliography=True)
    assert result.outcome == "success"
    assert not any(c[:2] == ["issue", "create"] for c in runner.calls)

    entries = ledger.read(tool="myarchivist", kind="catalog")
    assert entries[0].data["bibliography_issues"] == []


def test_scan_does_not_refile_open_bibliography_issue(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="9780441172719")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner(
        open_bibliography_issues=[
            {"number": 42, "title": "bibliography: catalog isbn:9780441172719"}
        ]
    )
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=ScriptedEngine("{}"),
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    result = archivist.scan(digital=[str(books)])
    assert result.outcome == "success"
    assert not any(c[:2] == ["issue", "create"] for c in runner.calls)


def test_rescan_with_weaker_engine_keeps_enrichment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    books = tmp_path / "books"
    books.mkdir()
    make_epub(books / "dune.epub", title="Dune", author="Frank Herbert", isbn="123")

    ledger = Ledger(tmp_path / "ledger.jsonl")
    runner = FakeRunner()
    reply = '{"tags": [{"id": 0, "tag": "fiction", "blurb": "A desert epic."}]}'
    first_engine = ScriptedEngine(reply)
    archivist = Archivist(
        source=repo,
        ledger=ledger,
        repo="owner/name",
        runner=runner,
        engine=first_engine,
        policy=_AllowPolicy(),
        fetch=empty_fetch,
    )
    assert archivist.scan(digital=[str(books)]).outcome == "success"
    assert len(first_engine.calls) == 1

    from conftest import SpyEngine

    noop_like = SpyEngine()
    archivist.engine = noop_like
    second = archivist.scan(digital=[str(books)])
    assert second.outcome == "skipped"
    assert noop_like.calls == []  # enrichment carried over, nothing pending

    committed = read_committed(repo, "my-archivist/catalog", "catalog/CATALOG.md")
    assert "A desert epic." in committed
