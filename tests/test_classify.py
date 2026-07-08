from __future__ import annotations

import json

from mythings.engine import NoopEngine

from conftest import ScriptedEngine
from myarchivist.catalog import CatalogEntry
from myarchivist.classify import classify_missing


def test_classify_missing_skips_entries_that_already_have_a_subject() -> None:
    entries = [CatalogEntry("Dune", "Frank Herbert", "123", ("physical",), subject="fiction")]
    engine = ScriptedEngine("{}")
    result = classify_missing(engine, entries)
    assert result[0].subject == "fiction"
    assert engine.calls == []  # never sent to the model


def test_classify_missing_batches_all_pending_in_one_call() -> None:
    entries = [
        CatalogEntry("Dune", "Frank Herbert", None, ("physical",)),
        CatalogEntry("Foundation", "Isaac Asimov", None, ("physical",)),
    ]
    reply = json.dumps(
        {
            "tags": [
                {"id": 0, "tag": "fiction", "blurb": "A desert epic."},
                {"id": 1, "tag": "fiction", "blurb": "Empire falls, psychohistory rises."},
            ]
        }
    )
    engine = ScriptedEngine(reply)
    result = classify_missing(engine, entries)
    assert len(engine.calls) == 1  # one Engine call for the whole batch
    assert result[0].subject == "fiction"
    assert result[1].blurb == "Empire falls, psychohistory rises."


def test_classify_missing_drops_invented_id() -> None:
    entries = [CatalogEntry("Dune", "Frank Herbert", None, ("physical",))]
    reply = json.dumps(
        {"tags": [{"id": 0, "tag": "fiction", "blurb": "x"}, {"id": 99, "tag": "other"}]}
    )
    result = classify_missing(ScriptedEngine(reply), entries)
    assert result[0].subject == "fiction"


def test_classify_missing_unknown_tag_falls_back_to_unsorted() -> None:
    entries = [CatalogEntry("Dune", "Frank Herbert", None, ("physical",))]
    reply = json.dumps({"tags": [{"id": 0, "tag": "made-up-genre", "blurb": ""}]})
    result = classify_missing(ScriptedEngine(reply), entries)
    assert result[0].subject == "unsorted"


def test_classify_missing_noop_engine_degrades() -> None:
    entries = [CatalogEntry("Dune", "Frank Herbert", None, ("physical",))]
    result = classify_missing(NoopEngine(), entries)
    assert result[0].subject == "unsorted"
    assert result[0].blurb == ""


def test_classify_missing_returns_unchanged_when_nothing_pending() -> None:
    entries = [CatalogEntry("Dune", "Frank Herbert", "123", ("physical",), subject="fiction")]
    result = classify_missing(NoopEngine(), entries)
    assert result == entries
