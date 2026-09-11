"""SQLite persistence.

Publication metadata + the resolver's `paragraphs` table are both here, so
`/resolve/{paragraphId}` is a primary-key lookup, not a JSONL scan. `paragraphs_prev`
retains each book's previous extracted text across a reprocess, cheaply, because the
bookmark re-anchoring flow needs something to diff against. `events` is a plain
append-only table with a monotonic (AUTOINCREMENT) cursor.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bookspine.models import Paragraph, PublicationRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    book_id        TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    identifier     TEXT NOT NULL,
    format         TEXT NOT NULL,
    status         TEXT NOT NULL,
    strategy       TEXT NOT NULL,
    source_hash    TEXT NOT NULL,
    canonical_hash TEXT NOT NULL,
    processed_at   TEXT NOT NULL,
    granularity    TEXT NOT NULL DEFAULT 'paragraph'
);

CREATE TABLE IF NOT EXISTS paragraphs (
    paragraph_id  TEXT PRIMARY KEY,
    book_id       TEXT NOT NULL,
    href          TEXT NOT NULL,
    text          TEXT NOT NULL,
    locator_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paragraphs_book_id ON paragraphs(book_id);

CREATE TABLE IF NOT EXISTS paragraphs_prev (
    book_id       TEXT NOT NULL,
    paragraph_id  TEXT NOT NULL,
    text          TEXT NOT NULL,
    archived_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paragraphs_prev_book_id ON paragraphs_prev(book_id);

CREATE TABLE IF NOT EXISTS events (
    cursor        INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id       TEXT NOT NULL,
    type          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: each call opens its own connection, used for exactly
    # one request/CLI invocation and then closed — never shared — but FastAPI can
    # run a sync dependency and its endpoint on different threadpool threads, which
    # sqlite3's default same-thread check would otherwise reject.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Lightweight forward-only migration for a prototype with no migration
    framework: add columns introduced after a db file was first created. Existing
    rows predate the `granularity` option, so they were paragraph-level — the
    column default already says so."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(publications)")}
    if "granularity" not in columns:
        conn.execute("ALTER TABLE publications ADD COLUMN granularity TEXT NOT NULL DEFAULT 'paragraph'")
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_publication(conn: sqlite3.Connection, record: PublicationRecord) -> None:
    conn.execute(
        """
        INSERT INTO publications
            (book_id, title, identifier, format, status, strategy, source_hash, canonical_hash, processed_at, granularity)
        VALUES (:book_id, :title, :identifier, :format, :status, :strategy, :source_hash, :canonical_hash, :processed_at, :granularity)
        ON CONFLICT(book_id) DO UPDATE SET
            title=excluded.title, identifier=excluded.identifier, format=excluded.format,
            status=excluded.status, strategy=excluded.strategy, source_hash=excluded.source_hash,
            canonical_hash=excluded.canonical_hash, processed_at=excluded.processed_at,
            granularity=excluded.granularity
        """,
        record.__dict__,
    )
    conn.commit()


def get_publication(conn: sqlite3.Connection, book_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM publications WHERE book_id = ?", (book_id,)).fetchone()
    if row is None:
        return None
    return {
        "bookId": row["book_id"],
        "title": row["title"],
        "identifier": row["identifier"],
        "format": row["format"],
        "status": row["status"],
        "strategy": row["strategy"],
        "granularity": row["granularity"],
        "sourceHash": row["source_hash"],
        "canonicalHash": row["canonical_hash"],
        "processedAt": row["processed_at"],
    }


def replace_paragraphs(conn: sqlite3.Connection, book_id: str, paragraphs: list[Paragraph]) -> None:
    """Archives the book's current paragraphs into `paragraphs_prev`, then replaces
    them. A no-op archive (0 rows) is normal for a brand-new book."""
    prev = conn.execute(
        "SELECT paragraph_id, text FROM paragraphs WHERE book_id = ?", (book_id,)
    ).fetchall()
    if prev:
        now = _now()
        conn.executemany(
            "INSERT INTO paragraphs_prev (book_id, paragraph_id, text, archived_at) VALUES (?, ?, ?, ?)",
            [(book_id, r["paragraph_id"], r["text"], now) for r in prev],
        )
    conn.execute("DELETE FROM paragraphs WHERE book_id = ?", (book_id,))
    conn.executemany(
        "INSERT INTO paragraphs (paragraph_id, book_id, href, text, locator_json) VALUES (?, ?, ?, ?, ?)",
        [(p.paragraph_id, p.book_id, p.href, p.text, json.dumps(p.locator.to_dict())) for p in paragraphs],
    )
    conn.commit()


def get_paragraph(conn: sqlite3.Connection, paragraph_id: str) -> dict | None:
    row = conn.execute(
        "SELECT paragraph_id, book_id, href, text, locator_json FROM paragraphs WHERE paragraph_id = ?",
        (paragraph_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "paragraphId": row["paragraph_id"],
        "bookId": row["book_id"],
        "href": row["href"],
        "text": row["text"],
        "locator": json.loads(row["locator_json"]),
    }


def list_paragraphs(conn: sqlite3.Connection, book_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT paragraph_id, book_id, href, text, locator_json FROM paragraphs WHERE book_id = ? ORDER BY rowid",
        (book_id,),
    ).fetchall()
    return [
        {
            "paragraphId": r["paragraph_id"],
            "bookId": r["book_id"],
            "href": r["href"],
            "text": r["text"],
            "locator": json.loads(r["locator_json"]),
        }
        for r in rows
    ]


def search_paragraphs(conn: sqlite3.Connection, book_id: str, query: str, limit: int) -> list[dict]:
    """Plain substring search over `text`, case-insensitive. Not FTS — a prototype
    keyword match, not ranked relevance."""
    rows = conn.execute(
        "SELECT paragraph_id, book_id, href, text, locator_json FROM paragraphs "
        "WHERE book_id = ? AND text LIKE ? ESCAPE '\\' ORDER BY rowid LIMIT ?",
        (book_id, _like_pattern(query), limit),
    ).fetchall()
    return [
        {
            "paragraphId": r["paragraph_id"],
            "bookId": r["book_id"],
            "href": r["href"],
            "text": r["text"],
            "locator": json.loads(r["locator_json"]),
        }
        for r in rows
    ]


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def append_event(conn: sqlite3.Connection, book_id: str, event_type: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO events (book_id, type, payload_json, created_at) VALUES (?, ?, ?, ?)",
        (book_id, event_type, json.dumps(payload), _now()),
    )
    conn.commit()
    return cur.lastrowid


def _event_row(r: sqlite3.Row) -> dict:
    return {
        "cursor": r["cursor"],
        "bookId": r["book_id"],
        "type": r["type"],
        "payload": json.loads(r["payload_json"]),
        "createdAt": r["created_at"],
    }


def list_events(conn: sqlite3.Connection, since: int) -> list[dict]:
    rows = conn.execute(
        "SELECT cursor, book_id, type, payload_json, created_at FROM events WHERE cursor > ? ORDER BY cursor ASC",
        (since,),
    ).fetchall()
    return [_event_row(r) for r in rows]


def list_events_since_time(conn: sqlite3.Connection, since_time: str) -> list[dict]:
    """`since_time` must already be normalized to the exact stored format
    (`%Y-%m-%dT%H:%M:%SZ`, UTC) — `created_at` comparison is a plain string
    comparison, which only sorts correctly when both sides share that format."""
    rows = conn.execute(
        "SELECT cursor, book_id, type, payload_json, created_at FROM events WHERE created_at > ? ORDER BY cursor ASC",
        (since_time,),
    ).fetchall()
    return [_event_row(r) for r in rows]
