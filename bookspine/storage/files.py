"""Content-addressed on-disk layout under a storage root:

  {root}/publications/{bookId}/record.json
  {root}/publications/{bookId}/structure.json
  {root}/publications/{bookId}/paragraphs.jsonl
  {root}/blobs/{sha256-hex}.epub           <- canonical EPUB, deduped by canonicalHash

Two identical processed outputs (same canonicalHash) share one blob on disk, for
free, just by writing to the same path.
"""

from __future__ import annotations

import json
from pathlib import Path


def publication_dir(root: str | Path, book_id: str) -> Path:
    d = Path(root) / "publications" / book_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def blob_path(root: str | Path, canonical_hash: str) -> Path:
    hexdigest = canonical_hash.split(":", 1)[-1]
    d = Path(root) / "blobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{hexdigest}.epub"


def store_blob(root: str | Path, canonical_hash: str, data: bytes) -> Path:
    path = blob_path(root, canonical_hash)
    if not path.exists():
        path.write_bytes(data)
    return path


def write_json(path: str | Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")
