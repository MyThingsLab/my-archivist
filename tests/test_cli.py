from __future__ import annotations

from pathlib import Path

import pytest

from myarchivist import cli


def test_cli_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_scan_skips_with_no_inputs(tmp_path: Path) -> None:
    code = cli.main(
        [
            "scan",
            "--source",
            str(tmp_path),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--no-pr",
            "--json",
        ]
    )
    assert code == 0
