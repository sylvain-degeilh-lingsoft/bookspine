"""On-disk layout under a storage root:

  {root}/publications/{bookId}/record.json
  {root}/publications/{bookId}/structure.json
  {root}/publications/{bookId}/paragraphs.jsonl

The EPUB itself is not kept — Thorium Web serves it from the content operator's
own storage. BookSpine only persists what it produced: structure, Locators, and
the paragraphId resolver index.
"""

from __future__ import annotations

import json
from pathlib import Path


def publication_dir(root: str | Path, book_id: str) -> Path:
    d = Path(root) / "publications" / book_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: str | Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")
