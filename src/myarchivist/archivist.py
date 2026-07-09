from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from myguard import Guard
from mythings.engine import Engine, NoopEngine
from mythings.github import GitHub, PullRequest, Runner, _gh, _pr_number
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import Action, Decision, Policy

from myarchivist.catalog import CatalogEntry, enrich_entries, merge_entries
from myarchivist.classify import classify_missing
from myarchivist.enrich import Fetcher
from myarchivist.enrich import _http as _default_fetch
from myarchivist.render import from_json, render_markdown, to_json
from myarchivist.scanner import read_physical_intake, scan_digital

_CATALOG_JSON = "catalog/catalog.json"
_CATALOG_MD = "catalog/CATALOG.md"
_BRANCH = "my-archivist/catalog"


class PolicyDenied(RuntimeError):
    pass


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
    ) -> Result:
        raw = scan_digital(digital or [])
        if physical:
            raw += read_physical_intake(physical)
        if not raw:
            return self._skip(0, "no digital files or physical intake rows given")

        enriched, subjects = enrich_entries(raw, fetch=self.fetch)
        merged = merge_entries(enriched, subjects_by_isbn=subjects)
        classified = classify_missing(self.engine, merged)

        try:
            pr, wrote = self._write(classified, no_pr=no_pr)
        except PolicyDenied as denied:
            self._record("failure", 0, str(denied), None)
            return Result("failure", 0, str(denied))

        if not wrote:
            return self._skip(len(classified), "catalog already up to date")

        detail = f"{len(classified)} entries ({len(raw)} scanned)"
        url = None if no_comment or issue is None else self._comment(issue, classified)
        self._record("success", len(classified), detail, pr.number if pr else None, url)
        return Result("success", len(classified), detail, pr.number if pr else None, url)

    def _write(
        self, entries: list[CatalogEntry], *, no_pr: bool
    ) -> tuple[PullRequest | None, bool]:
        existing_pr = None if no_pr else self._existing_pr()
        # Diff against the tool's own open PR branch if one exists (so a
        # re-run before merge still detects "no change"), else against base.
        base_ref = _BRANCH if existing_pr is not None else self.base
        with Workspace(self.source, base_ref) as tree:
            existing_path = tree / _CATALOG_JSON
            existing = (
                from_json(existing_path.read_text(encoding="utf-8"))
                if existing_path.exists()
                else []
            )
            if existing == entries:
                return existing_pr, False

            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_text(to_json(entries), encoding="utf-8")
            (tree / _CATALOG_MD).write_text(render_markdown(entries), encoding="utf-8")

            self._git(tree, ["checkout", "-B", _BRANCH])
            self._git(tree, ["add", _CATALOG_JSON, _CATALOG_MD])
            self._git(tree, ["commit", "-m", "catalog: refresh from scan"])
            if no_pr:
                # The commit stays on the local branch after the worktree is
                # torn down — --no-pr must not silently discard the catalog.
                return None, True
            # The tool's own dedicated branch; force-push is the intended
            # refresh, never touches a shared branch (same as MyTodo).
            self._git(tree, ["push", "--force", "-u", "origin", _BRANCH])
        if existing_pr is not None:
            return existing_pr, True
        self._guard(f"gh pr create --head {_BRANCH} --base {self.base}")
        pr = self.github.open_pr(
            title="catalog: refresh from scan",
            body="Refreshed catalog/CATALOG.md + catalog/catalog.json from the latest scan.",
            base=self.base,
            head=_BRANCH,
        )
        return pr, True

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
        self, outcome: str, count: int, detail: str, pr: int | None, comment_url: str | None = None
    ) -> None:
        self.ledger.record(
            tool="myarchivist",
            kind="catalog",
            outcome=outcome,
            detail=detail,
            new_entries=count,
            pr=pr,
            comment_url=comment_url,
        )
