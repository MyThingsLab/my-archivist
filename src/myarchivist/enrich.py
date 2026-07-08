from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable

# The one network boundary. Default shells out to urllib; tests inject a fake so
# the HTTP call is the only thing mocked (same discipline as engine/github Runners).
Fetcher = Callable[..., bytes]

OPENLIBRARY_ENDPOINT = "https://openlibrary.org/api/books"

# A small keyword classifier over Open Library subjects — a closed vocabulary,
# the same discipline the Engine step's tag falls back to (never invented).
_SUBJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fiction": ("fiction", "novel", "fantasy", "science fiction"),
    "technical": ("programming", "computer", "engineering", "mathematics", "physics"),
    "reference": ("reference", "dictionary", "encyclopedia", "handbook"),
}


def _http(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https endpoint
        return resp.read()


def lookup_isbn(isbn: str, *, fetch: Fetcher = _http) -> dict | None:
    key = f"ISBN:{isbn}"
    params = urllib.parse.urlencode({"bibkeys": key, "format": "json", "jscmd": "data"})
    raw = fetch(f"{OPENLIBRARY_ENDPOINT}?{params}")
    payload = json.loads(raw)
    return payload.get(key)


def title_author_from_lookup(data: dict) -> tuple[str, str]:
    title = (data.get("title") or "").strip()
    authors = ", ".join(a.get("name", "").strip() for a in data.get("authors", []) if a.get("name"))
    return title, authors


def classify_subject(subjects: list[str]) -> str | None:
    haystack = " ".join(s.lower() for s in subjects)
    for tag, keywords in _SUBJECT_KEYWORDS.items():
        if any(kw in haystack for kw in keywords):
            return tag
    return "non-fiction" if subjects else None


def subjects_from_lookup(data: dict) -> list[str]:
    return [s.get("name", "") for s in data.get("subjects", []) if s.get("name")]
