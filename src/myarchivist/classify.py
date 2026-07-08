from __future__ import annotations

import json
from dataclasses import replace

from mythings.engine import Engine, EngineRequest

from myarchivist.catalog import CatalogEntry

_TAGS = ("fiction", "non-fiction", "technical", "reference", "other")

_SYSTEM = (
    "For each numbered book below, assign exactly one subject tag from this "
    f"closed set: {', '.join(_TAGS)}, plus a one-line blurb. Only use the "
    "given numeric ids -- never invent one. Reply with a single JSON object "
    "and nothing else."
)


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _prompt(pending: list[tuple[int, CatalogEntry]]) -> str:
    lines = ["Books:"]
    for i, entry in pending:
        lines.append(f"{i}. Title: {entry.title} | Author: {entry.author}")
    lines.append(
        '\nReturn JSON: {"tags": [{"id": <int>, "tag": <string>, "blurb": <string>}, ...]}'
    )
    return "\n".join(lines)


def classify_missing(engine: Engine, entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """One Engine call classifies every entry still missing a subject.

    Entries a deterministic ISBN-subject lookup already resolved are left
    untouched and never sent to the model.
    """
    pending = [(i, e) for i, e in enumerate(entries) if e.subject is None]
    if not pending:
        return entries

    reply = engine.run(
        EngineRequest(
            system=_SYSTEM,
            prompt=_prompt(pending),
            context={"pending_count": len(pending)},
        )
    )
    obj = _parse_json_object(reply.text)
    tags_by_id: dict[int, tuple[str, str]] = {}
    if obj is not None:
        for item in obj.get("tags") or []:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if idx not in {i for i, _ in pending}:  # drop any id the model invented
                continue
            tag = str(item.get("tag", "")).strip().lower()
            if tag not in _TAGS:
                tag = "unsorted"
            tags_by_id[idx] = (tag, str(item.get("blurb", "")).strip())

    result = list(entries)
    for idx, entry in pending:
        tag, blurb = tags_by_id.get(idx, ("unsorted", ""))
        result[idx] = replace(entry, subject=tag, blurb=blurb)
    return result
