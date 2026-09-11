"""Ties the pure extraction pipeline to persistence (SQLite + content-addressed
files). Shared by the CLI and the API so both go through the same idempotency and
event-emission logic."""

from __future__ import annotations

import logging
import sqlite3

import httpx

from bookspine.extract import pipeline
from bookspine.storage import db, files

logger = logging.getLogger("bookspine")


def process_epub(
    conn: sqlite3.Connection,
    storage_root: str,
    epub_path: str,
    strategy: str = "auto",
    notify_url: str | None = None,
    granularity: str = "paragraph",
) -> tuple[dict, bool]:
    """Runs extraction and persists the result. Returns (record_dict, unchanged).

    `unchanged` is True when the submitted file's sourceHash *and* the requested
    strategy/granularity all match what's already stored for this bookId — an
    idempotent no-op, not a reprocess (§05/§07: sourceHash exists precisely so a
    resubmission of unchanged content is cheap and detectable). Matching sourceHash
    alone isn't enough: re-submitting the same file asking for a different
    strategy or granularity is real, new work, not a no-op.
    """
    result = pipeline.extract(epub_path, strategy, granularity)
    book_id = result.record.book_id

    existing = db.get_publication(conn, book_id)
    if (
        existing is not None
        and existing["sourceHash"] == result.record.source_hash
        and existing["strategy"] == result.record.strategy
        and existing["granularity"] == result.record.granularity
    ):
        logger.info("publication %s: sourceHash/strategy/granularity unchanged, skipping reprocess", book_id)
        return existing, True

    pub_dir = files.publication_dir(storage_root, book_id)
    files.write_json(pub_dir / "record.json", result.record.to_dict())
    files.write_json(pub_dir / "structure.json", result.structure.to_dict())
    files.write_jsonl(
        pub_dir / "paragraphs.jsonl",
        [
            {"paragraphId": p.paragraph_id, "href": p.href, "text": p.text, "locator": p.locator.to_dict()}
            for p in result.paragraphs
        ],
    )
    files.store_blob(storage_root, result.record.canonical_hash, result.canonical_epub)

    db.upsert_publication(conn, result.record)
    db.replace_paragraphs(conn, book_id, result.paragraphs)

    event_type = "publication.updated" if existing else "publication.ready"
    db.append_event(conn, book_id, event_type, result.record.to_dict())

    if notify_url:
        _notify(notify_url, result.record.to_dict())

    return result.record.to_dict(), False


def _notify(notify_url: str, record: dict) -> None:
    """Best-effort webhook call. A failed notification never fails the request that
    triggered it — the event feed (`GET /v1/events`) is the durable source of truth,
    the webhook is just a nudge to poll it sooner."""
    try:
        httpx.post(notify_url, json=record, timeout=5.0)
    except httpx.HTTPError as exc:
        logger.warning("notifyUrl POST to %s failed: %s", notify_url, exc)
