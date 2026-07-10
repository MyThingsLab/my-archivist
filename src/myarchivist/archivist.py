from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from myguard import Guard
from mythings.engine import Engine, NoopEngine
from mythings.github import GitHub, GitHubError, PullRequest, Runner, _gh, _pr_number
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import Action, Decision, Policy

from myarchivist.catalog import (
    CatalogEntry,
    _entry_key,
    carry_enrichment,
    enrich_entries,
    merge_entries,
)
from myarchivist.classify import classify_missing
from myarchivist.enrich import Fetcher
from myarchivist.enrich import _http as _default_fetch
from myarchivist.render import from_json, render_markdown, to_json
from myarchivist.scanner import read_physical_intake, scan_digital

_CATALOG_JSON = "catalog/catalog.json"
_CATALOG_MD = "catalog/CATALOG.md"
_BRANCH = "my-archivist/catalog"
BIBLIOGRAPHY_LABEL = "my-bibliography"


class PolicyDenied(RuntimeError):
    pass


def _new_isbn_entries(
    entries: list[CatalogEntry], existing: list[CatalogEntry]
) -> list[CatalogEntry]:
    known = {_entry_key(e) for e in existing}
    return [e for e in entries if e.isbn and _entry_key(e) not in known]


@dataclass(frozen=True)
class Result:
    outcome: str  # success | skipped | failure
    new_entries: int
    detail: str
    pr: int | None = None
    comment_url: str | None = None


class Archivist:
    def __init__(
        self,
        *,
        source: str | Path,
        ledger: Ledger,
        repo: str | None = None,
        base: str = "main",
        engine: Engine | None = None,
        policy: Policy | None = None,
        runner: Runner = _gh,
        fetch: Fetcher = _default_fetch,
    ) -> None:
        self.source = Path(source)
        self.ledger = ledger
        self.repo = repo
        self.base = base
        self.engine: Engine = engine or NoopEngine()
        self.policy: Policy = policy or Guard()
        self.runner = runner
        self.github = GitHub(repo, runner=runner)
        self.fetch = fetch

    def scan(
        self,
        *,
        digital: list[str] | None = None,
        physical: str | None = None,
        issue: int | None = None,
        no_pr: bool = False,
        no_comment: bool = False,
        no_bibliography: bool = False,
    ) -> Result:
        raw = scan_digital(digital or [])
        if physical:
            raw += read_physical_intake(physical)
        if not raw:
            return self._skip(0, "no digital files or physical intake rows given")

        enriched, subjects = enrich_entries(raw, fetch=self.fetch)
        merged = merge_entries(enriched, subjects_by_isbn=subjects)

        existing_pr = None if no_pr else self._existing_pr()
        # Diff against the tool's own catalog branch when one exists — the
        # open PR branch, or the local branch on a --no-pr run — so a re-run
        # before merge still detects "no change"; else against base.
        if no_pr:
            base_ref = _BRANCH if self._local_branch_exists() else self.base
        else:
            base_ref = _BRANCH if existing_pr is not None else self.base

        merged = carry_enrichment(merged, self._read_catalog(base_ref))
        classified = classify_missing(self.engine, merged)

        try:
            pr, wrote, new_isbn_entries = self._write(
                classified, existing_pr=existing_pr, base_ref=base_ref, no_pr=no_pr
            )
        except PolicyDenied as denied:
            self._record("failure", 0, str(denied), None)
            return Result("failure", 0, str(denied))

        if not wrote:
            return self._skip(len(classified), "catalog already up to date")

        bibliography_issues = (
            [] if no_bibliography else self._file_bibliography_issues(new_isbn_entries)
        )

        detail = f"{len(classified)} entries ({len(raw)} scanned)"
        if bibliography_issues:
            detail += f", filed {len(bibliography_issues)} bibliography issue(s)"
        url = None if no_comment or issue is None else self._comment(issue, classified)
        self._record(
            "success",
            len(classified),
            detail,
            pr.number if pr else None,
            url,
            bibliography_issues=bibliography_issues,
        )
        return Result("success", len(classified), detail, pr.number if pr else None, url)

    def _write(
        self,
        entries: list[CatalogEntry],
        *,
        existing_pr: PullRequest | None,
        base_ref: str,
        no_pr: bool,
    ) -> tuple[PullRequest | None, bool, list[CatalogEntry]]:
        with Workspace(self.source, base_ref) as tree:
            existing_path = tree / _CATALOG_JSON
            existing = (
                from_json(existing_path.read_text(encoding="utf-8"))
                if existing_path.exists()
                else []
            )
            if existing == entries:
                return existing_pr, False, []

            new_isbn_entries = _new_isbn_entries(entries, existing)
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_text(to_json(entries), encoding="utf-8")
            (tree / _CATALOG_MD).write_text(render_markdown(entries), encoding="utf-8")

            self._git(tree, ["checkout", "-B", _BRANCH])
            self._git(tree, ["add", _CATALOG_JSON, _CATALOG_MD])
            self._git(tree, ["commit", "-m", "catalog: refresh from scan"])
            if no_pr:
                # The commit stays on the local branch after the worktree is
                # torn down — --no-pr must not silently discard the catalog.
                return None, True, new_isbn_entries
            # The tool's own dedicated branch; force-push is the intended
            # refresh, never touches a shared branch (same as MyTodo).
            self._git(tree, ["push", "--force", "-u", "origin", _BRANCH])
        if existing_pr is not None:
            return existing_pr, True, new_isbn_entries
        self._guard(f"gh pr create --head {_BRANCH} --base {self.base}")
        pr = self.github.open_pr(
            title="catalog: refresh from scan",
            body="Refreshed catalog/CATALOG.md + catalog/catalog.json from the latest scan.",
            base=self.base,
            head=_BRANCH,
        )
        return pr, True, new_isbn_entries

    def _read_catalog(self, ref: str) -> list[CatalogEntry]:
        proc = subprocess.run(
            ["git", "-C", str(self.source), "show", f"{ref}:{_CATALOG_JSON}"],
            capture_output=True,
            text=True,
        )
        return from_json(proc.stdout) if proc.returncode == 0 else []

    def _local_branch_exists(self) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.source), "rev-parse", "--verify", "--quiet", _BRANCH],
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0

    def _existing_pr(self) -> PullRequest | None:
        if self.repo is None:
            return None
        argv = ["pr", "list", "--head", _BRANCH, "--state", "open", "--json", "number,url"]
        argv += ["--repo", self.repo]
        rows = json.loads(self.runner(argv))
        if not rows:
            return None
        row = rows[0]
        return PullRequest(number=row.get("number") or _pr_number(row["url"]), url=row["url"])

    def _file_bibliography_issues(self, new_isbn_entries: list[CatalogEntry]) -> list[dict]:
        # Every newly-cataloged ISBN already carries a locator my-bibliography
        # understands verbatim ("isbn:<isbn>"). Filed as a plain labeled issue,
        # not a package call -- my-bibliography is a fully independent tool,
        # same fence as MyResearcher filing arXiv-cited issues for it.
        if self.repo is None:
            return []
        existing_titles: set[str] | None = None
        filed: list[dict] = []
        for entry in new_isbn_entries:
            locator = f"isbn:{entry.isbn}"
            title = f"bibliography: catalog {locator}"
            if existing_titles is None:
                existing_titles = self._open_bibliography_titles()
            if title in existing_titles:
                continue
            action = Action(kind="bash", payload={"command": f"gh issue create --title {title!r}"})
            gate = self.policy.evaluate(action).under(unattended=in_github_actions())
            if gate is not Decision.ALLOW:
                continue
            body = f"{locator}\n\nCataloged from `{entry.title}` by {entry.author or 'unknown'}."
            created = self.github.create_issue(title=title, body=body)
            self.github.add_labels(created.number, [BIBLIOGRAPHY_LABEL])
            filed.append({"isbn": entry.isbn, "issue": created.number})
        return filed

    def _open_bibliography_titles(self) -> set[str]:
        try:
            issues = self.github.list_issues(labels=[BIBLIOGRAPHY_LABEL], state="open", limit=100)
        except GitHubError:
            return set()
        return {i.title for i in issues}

    def _comment(self, issue: int, entries: list[CatalogEntry]) -> str | None:
        if self.repo is None:
            return None
        body = render_markdown(entries)
        argv = ["issue", "comment", str(issue), "--repo", self.repo, "--body", body]
        action = Action(kind="bash", payload={"command": f"gh issue comment {issue}"})
        if self.policy.evaluate(action).under(unattended=in_github_actions()) is not Decision.ALLOW:
            return None
        return self.runner(argv).strip() or None

    def _git(self, tree: Path, argv: list[str]) -> None:
        self._guard("git " + " ".join(argv))
        proc = subprocess.run(["git", "-C", str(tree), *argv], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")

    def _guard(self, command: str) -> None:
        result = self.policy.evaluate(Action(kind="bash", payload={"command": command}))
        if result.under(unattended=in_github_actions()) is not Decision.ALLOW:
            raise PolicyDenied(f"policy blocked: {command} ({result.reason or result.decision})")

    def _skip(self, count: int, detail: str) -> Result:
        self._record("skipped", count, detail, None)
        return Result("skipped", count, detail)

    def _record(
        self,
        outcome: str,
        count: int,
        detail: str,
        pr: int | None,
        comment_url: str | None = None,
        *,
        bibliography_issues: list[dict] | None = None,
    ) -> None:
        self.ledger.record(
            tool="myarchivist",
            kind="catalog",
            outcome=outcome,
            detail=detail,
            new_entries=count,
            pr=pr,
            comment_url=comment_url,
            bibliography_issues=bibliography_issues or [],
        )
